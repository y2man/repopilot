import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent, PointerEvent as ReactPointerEvent, ReactNode } from 'react'
import { request } from './lib/api'
import { AnimatePresence, animate, motion, useMotionValue, useMotionValueEvent, useReducedMotion, useSpring, useTransform } from 'framer-motion'
import {
  Activity, ArrowUpRight, Bot, BrainCircuit, Check, ChevronRight,
  Command, Copy, FileCode2, FolderGit2, Github, LayoutDashboard, LoaderCircle,
  LogOut, Menu, MessageSquareText, Plus, Search, Send, Settings2, ShieldCheck, Sparkles,
  UploadCloud, X, Zap, RefreshCw, Trash2, FileText, Network,
} from 'lucide-react'

type Section = 'Overview' | 'Repositories' | 'Repository Details' | 'Architecture' | 'AI Workspace' | 'Code Explorer' | 'Search' | 'Code Review' | 'Debugging' | 'Agent Activity' | 'Settings'
type Repo = { id:number; name:string; source:string; status:string; file_count:number; chunk_count:number; created_at:string; last_indexed_at?:string|null }
type RepoFile = { id:number; path:string; language:string; line_count:number }
type Source = { path:string; language:string; start_line:number; end_line:number; score:number }
type Health = {status:string;database:string;redis:string;vector_store:string;ai_configured:boolean;embeddings_installed:boolean;tree_sitter_installed:boolean;reranker_enabled:boolean;github_oauth_configured:boolean}
type ChatMessage = { role:'user'|'assistant'; content:string; sources?:Source[] }
type AuditEvent = {id:number;action:string;resource_type:string;resource_id:string;repository_id:number|null;status:string;details:Record<string,unknown>;created_at:string}
type IndexJob = {id:number;status:string;progress:number;detail:string;created_at:string}
const API = (import.meta.env.VITE_API_URL || '').trim().replace(/\/+$/, '')
const nav: {label:Section;icon:typeof LayoutDashboard}[] = [
  {label:'Overview',icon:LayoutDashboard},{label:'Repositories',icon:FolderGit2},{label:'Repository Details',icon:FileText},{label:'Architecture',icon:Network},
  {label:'AI Workspace',icon:BrainCircuit},{label:'Code Explorer',icon:FileCode2},{label:'Search',icon:Search},
  {label:'Code Review',icon:ShieldCheck},{label:'Debugging',icon:Zap},{label:'Agent Activity',icon:Activity},{label:'Settings',icon:Settings2},
]

function GlassCard({children,className='',delay=0}:{children:ReactNode;className?:string;delay?:number}) {
  const reduce = useReducedMotion()
  const pointerX = useMotionValue(0)
  const pointerY = useMotionValue(0)
  const rotateX = useSpring(useTransform(pointerY,[-0.5,0.5],[2.5,-2.5]),{stiffness:180,damping:24})
  const rotateY = useSpring(useTransform(pointerX,[-0.5,0.5],[-2.5,2.5]),{stiffness:180,damping:24})
  const handlePointerMove = (event:ReactPointerEvent<HTMLElement>) => {
    if(reduce || event.pointerType!=='mouse') return
    const rect=event.currentTarget.getBoundingClientRect()
    const x=(event.clientX-rect.left)/rect.width
    const y=(event.clientY-rect.top)/rect.height
    pointerX.set(x-.5);pointerY.set(y-.5)
    event.currentTarget.style.setProperty('--spot-x',`${x*100}%`)
    event.currentTarget.style.setProperty('--spot-y',`${y*100}%`)
  }
  const resetPointer = (event:ReactPointerEvent<HTMLElement>) => {
    pointerX.set(0);pointerY.set(0)
    event.currentTarget.style.setProperty('--spot-x','50%')
    event.currentTarget.style.setProperty('--spot-y','0%')
  }
  return <motion.section className={`glass-card ${className}`} style={reduce?undefined:{rotateX,rotateY,transformPerspective:1000}} onPointerMove={handlePointerMove} onPointerLeave={resetPointer} initial={reduce?false:{opacity:0,y:15,filter:'blur(5px)'}} animate={{opacity:1,y:0,filter:'blur(0px)'}} transition={{duration:reduce?0:.45,delay}} whileHover={reduce?undefined:{y:-3}} whileTap={reduce?undefined:{scale:.995}}>{children}</motion.section>
}
function App() {
  const reduceMotion = useReducedMotion()
  const [token,setToken] = useState<string|null>(()=>sessionStorage.getItem('rp-token'))
  const [email,setEmail] = useState('')
  const [password,setPassword] = useState('')
  const [register,setRegister] = useState(false)
  const [authBusy,setAuthBusy] = useState(false)
  const [authError,setAuthError] = useState('')
  const [userEmail,setUserEmail] = useState('')
  const [health,setHealth] = useState<Health|null>(null)
  const [healthLoaded,setHealthLoaded] = useState(false)
  const [active,setActive] = useState<Section>('Overview')
  const [repos,setRepos] = useState<Repo[]>([])
  const [selectedRepo,setSelectedRepo] = useState<number|null>(null)
  const [files,setFiles] = useState<RepoFile[]>([])
  const [filesLoading,setFilesLoading] = useState(false)
  const [selectedFile,setSelectedFile] = useState<{path:string;language:string;content:string}|null>(null)
  const [highlightRange,setHighlightRange] = useState<{start:number;end:number}|null>(null)
  const [messages,setMessages] = useState<ChatMessage[]>([])
  const [conversationId,setConversationId] = useState<number|null>(null)
  const [conversations,setConversations] = useState<Array<{id:number;title:string;updated_at:string}>>([])
  const [githubUrl,setGithubUrl] = useState('')
  const [githubBusy,setGithubBusy] = useState(false)
  const [githubConnected,setGithubConnected] = useState(false)
  const [auditEvents,setAuditEvents] = useState<AuditEvent[]>([])
  const [reviewResult,setReviewResult] = useState('')
  const [agentTask,setAgentTask] = useState('Trace the authentication flow and identify important dependencies.')
  const [agentBusy,setAgentBusy] = useState(false)
  const [testRun,setTestRun] = useState<{status:string;exit_code:number|null;output:string;duration_seconds:number;timed_out:boolean}|null>(null)
  const [testBusy,setTestBusy] = useState(false)
  const [agentRuns,setAgentRuns] = useState<Array<{id:number;task:string;status:string;result:string;created_at:string}>>([])
  const [indexJobs,setIndexJobs] = useState<IndexJob[]>([])
  const [prompt,setPrompt] = useState('')
  const [pendingQuestion,setPendingQuestion] = useState<string|null>(null)
  const [loading,setLoading] = useState(false)
  const [chatBusy,setChatBusy] = useState(false)
  const [chatPhase,setChatPhase] = useState<'retrieving'|'streaming'>('retrieving')
  const [uploading,setUploading] = useState(false)
  const [toast,setToast] = useState('')
  const [error,setError] = useState('')
  const [mobileNav,setMobileNav] = useState(false)
  const [search,setSearch] = useState('')
  const [globalQuery,setGlobalQuery] = useState('')
  const [searchResults,setSearchResults] = useState<Array<{path:string;language:string;start_line:number;end_line:number;content:string;score:number}>>([])
  const [debugInput,setDebugInput] = useState('')
  const [debugResult,setDebugResult] = useState('')
  const [patchInstruction,setPatchInstruction] = useState('')
  const [testFilePath,setTestFilePath] = useState('tests/test_generated.py')
  const [patchProposal,setPatchProposal] = useState<{id:number;diff:string;explanation:string;status:string}|null>(null)
  const [patchBusy,setPatchBusy] = useState(false)
  const [approvedPatchId,setApprovedPatchId] = useState<number|null>(null)
  const [publishedPatchId,setPublishedPatchId] = useState<number|null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const chatEnd = useRef<HTMLDivElement>(null)
  const codeViewer = useRef<HTMLPreElement>(null)
  const activeRepo = repos.find(r=>r.id===selectedRepo) || null
  useEffect(()=>{setApprovedPatchId(null);setPublishedPatchId(null);setPatchProposal(null)},[selectedRepo])
  const notify = useCallback((s:string)=>{setToast(s);window.setTimeout(()=>setToast(''),3200)},[])

  const refreshRepos = useCallback(async (auth=token)=>{
    if (!auth) return
    const data = await request<Repo[]>('/api/v1/repositories',auth)
    setRepos(data)
    setSelectedRepo(current=>current && data.some(r=>r.id===current)?current:(data[0]?.id??null))
  },[token])
  useEffect(()=>{
    let alive=true
    const loadHealth=()=>request<Health>('/health',null).then(value=>{if(alive){setHealth(value);setHealthLoaded(true)}}).catch(()=>{if(alive){setHealth(null);setHealthLoaded(true)}})
    loadHealth()
    const timer=window.setInterval(loadHealth,30000)
    return ()=>{alive=false;window.clearInterval(timer)}
  },[])
  useEffect(()=>{
    if (!token) return
    request<{id:number;email:string}>('/api/v1/auth/me',token).then(async u=>{setUserEmail(u.email);const status=await request<{connected:boolean}>('/api/v1/auth/github/status',token);setGithubConnected(status.connected);return refreshRepos(token)}).catch(()=>{sessionStorage.removeItem('rp-token');setToken(null)})
  },[token,refreshRepos])
  useEffect(()=>{
    if (!token || !selectedRepo) {setFiles([]);setSelectedFile(null);setFilesLoading(false);return}
    let alive=true
    setFilesLoading(true)
    request<RepoFile[]>(`/api/v1/repositories/${selectedRepo}/files`,token).then(rows=>{if(alive)setFiles(rows)}).catch(e=>{if(alive)setError(e.message)}).finally(()=>{if(alive)setFilesLoading(false)})
    return ()=>{alive=false}
  },[token,selectedRepo])
  useEffect(()=>{chatEnd.current?.scrollIntoView({behavior:'smooth',block:'end'})},[messages,loading])
  useEffect(()=>{
    if(!token||active!=='Settings')return
    request<AuditEvent[]>('/api/v1/audit?limit=50',token).then(setAuditEvents).catch(e=>setError(e instanceof Error?e.message:'Could not load audit history'))
  },[token,active])
  useEffect(()=>{
    if(!token||!selectedRepo||active!=='AI Workspace'){setConversations([]);return}
    request<typeof conversations>(`/api/v1/conversations?repository_id=${selectedRepo}`,token).then(setConversations).catch(e=>setError(e instanceof Error?e.message:'Could not load conversation history'))
  },[token,selectedRepo,active,conversationId])
  useEffect(()=>{if(highlightRange){const behavior=window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth';codeViewer.current?.querySelector('.citation-highlight')?.scrollIntoView({behavior,block:'center'})}},[selectedFile,highlightRange])
  useEffect(()=>{
    if(!token||!selectedRepo||!['Overview','Architecture','Agent Activity'].includes(active)){setIndexJobs([]);return}
    let alive=true
    const loadJobs=()=>request<typeof indexJobs>(`/api/v1/repositories/${selectedRepo}/jobs`,token).then(rows=>{if(alive)setIndexJobs(rows)}).catch(()=>{})
    loadJobs()
    const timer=window.setInterval(loadJobs,5000)
    return ()=>{alive=false;window.clearInterval(timer)}
  },[token,selectedRepo,active])
  useEffect(()=>{
    if(!token||!selectedRepo||active!=='Agent Activity'){setAgentRuns([]);return}
    let alive=true
    const load=()=>request<typeof agentRuns>(`/api/v1/agent/executions?repository_id=${selectedRepo}`,token).then(rows=>{if(alive)setAgentRuns(rows)}).catch(()=>{})
    load()
    const timer=window.setInterval(load,5000)
    return ()=>{alive=false;window.clearInterval(timer)}
  },[token,selectedRepo,active])
  useEffect(()=>{
    if(reduceMotion)return
    const timers=new Set<number>()
    const onPointerMove=(event:PointerEvent)=>{
      if(event.pointerType!=='mouse')return
      document.documentElement.style.setProperty('--pointer-x',`${event.clientX}px`)
      document.documentElement.style.setProperty('--pointer-y',`${event.clientY}px`)
      const target=event.target instanceof Element?event.target.closest<HTMLElement>('button:not([disabled])'):null
      if(!target)return
      target.classList.add('magnetic-button')
      const rect=target.getBoundingClientRect()
      target.style.setProperty('--magnetic-x',`${((event.clientX-rect.left)/rect.width-.5)*5}px`)
      target.style.setProperty('--magnetic-y',`${((event.clientY-rect.top)/rect.height-.5)*5}px`)
      target.style.setProperty('--ripple-x',`${event.clientX-rect.left}px`)
      target.style.setProperty('--ripple-y',`${event.clientY-rect.top}px`)
    }
    const onPointerDown=(event:PointerEvent)=>{
      if(!(event.target instanceof Element))return
      const target=event.target.closest<HTMLElement>('button:not([disabled])')
      if(!target)return
      const rect=target.getBoundingClientRect()
      target.style.setProperty('--ripple-x',`${event.clientX-rect.left}px`)
      target.style.setProperty('--ripple-y',`${event.clientY-rect.top}px`)
    }
    const resetButton=(event:PointerEvent)=>{
      if(!(event.target instanceof Element))return
      const target=event.target.closest<HTMLElement>('button:not([disabled])')
      if(!target||event.relatedTarget instanceof Node&&target.contains(event.relatedTarget))return
      target.style.setProperty('--magnetic-x','0px')
      target.style.setProperty('--magnetic-y','0px')
      target.classList.remove('magnetic-button')
    }
    const onClick=(event:MouseEvent)=>{
      if(!(event.target instanceof Element))return
      const target=event.target.closest<HTMLElement>('button:not([disabled])')
      if(!target)return
      target.classList.remove('ripple-feedback')
      void target.offsetWidth
      target.classList.add('ripple-feedback')
      const timer=window.setTimeout(()=>{target.classList.remove('ripple-feedback');timers.delete(timer)},500)
      timers.add(timer)
    }
    document.addEventListener('pointermove',onPointerMove,{passive:true})
    document.addEventListener('pointerdown',onPointerDown)
    document.addEventListener('pointerout',resetButton)
    document.addEventListener('click',onClick)
    return ()=>{
      document.removeEventListener('pointermove',onPointerMove)
      document.removeEventListener('pointerdown',onPointerDown)
      document.removeEventListener('pointerout',resetButton)
      document.removeEventListener('click',onClick)
      timers.forEach(window.clearTimeout)
      document.documentElement.style.removeProperty('--pointer-x')
      document.documentElement.style.removeProperty('--pointer-y')
    }
  },[reduceMotion])

  const submitAuth = async (e:FormEvent)=>{
    e.preventDefault();setAuthBusy(true);setAuthError('')
    try {
      const data = await request<{access_token:string;user:{email:string}}>(`/api/v1/auth/${register?'register':'login'}`,null,{method:'POST',body:JSON.stringify({email,password})})
      sessionStorage.setItem('rp-token',data.access_token);setToken(data.access_token);setUserEmail(data.user.email);setPassword('')
    } catch(e) {setAuthError(e instanceof Error?e.message:'Authentication failed')} finally {setAuthBusy(false)}
  }
  const logout=()=>{sessionStorage.removeItem('rp-token');setToken(null);setRepos([]);setMessages([]);setSelectedRepo(null);setUserEmail('')}
  const upload=async(file:File)=>{
    if (!token) return
    setUploading(true);setError('')
    const form=new FormData();form.append('file',file)
    try {await request<Repo>('/api/v1/repositories/upload',token,{method:'POST',body:form});await refreshRepos();notify('Repository uploaded and indexed successfully.')} catch(e){setError(e instanceof Error?e.message:'Upload failed')} finally {setUploading(false);if(fileInput.current)fileInput.current.value=''}
  }
  const openFile=async(path:string,start?:number,end?:number)=>{
    setHighlightRange(start&&end?{start,end}:null)
    if (!token || !selectedRepo) return
    try {const data=await request<{path:string;language:string;content:string}>(`/api/v1/repositories/${selectedRepo}/files/content?path=${encodeURIComponent(path)}`,token);setSelectedFile(data);setActive('Code Explorer')} catch(e){setError(e instanceof Error?e.message:'Could not open file')}
  }
  const loadConversation=async(id:number)=>{
    if(!token)return
    try{const rows=await request<Array<{role:'user'|'assistant';content:string;sources?:Source[]}>>(`/api/v1/conversations/${id}/messages`,token);setConversationId(id);setMessages(rows.map(row=>({role:row.role,content:row.content,sources:row.sources||[]})));setError('')}
    catch(e){setError(e instanceof Error?e.message:'Could not load conversation')}
  }
  const sendQuestion=async(question=prompt,repositoryId=selectedRepo)=>{
    if (!token || !repositoryId || question.trim().length<3) return
    const q=question.trim();setPrompt('');setMessages(m=>[...m,{role:'user',content:q},{role:'assistant',content:''}]);setChatPhase('retrieving');setChatBusy(true);setError('')
    try {
      const response=await fetch(`${API}/api/v1/chat/stream`,{method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:JSON.stringify({repository_id:repositoryId,question:q,conversation_id:conversationId})})
      if(!response.ok){let detail=`Request failed (${response.status})`;try{detail=(await response.json()).detail||detail}catch{/* no JSON body */}throw new Error(detail)}
      if(!response.body)throw new Error('Streaming response body is unavailable')
      const reader=response.body.getReader();const decoder=new TextDecoder();let buffer='';let completed=false
      const consume=(block:string)=>{
        const dataLine=block.split('\n').find(line=>line.startsWith('data:'))
        if(!dataLine)return
        const event=JSON.parse(dataLine.slice(5).trim()) as {status?:'retrieving'|'generating';token?:string;done?:boolean;conversation_id?:number;sources?:Source[];detail?:string}
        if(event.status==='retrieving')setChatPhase('retrieving')
        if(event.status==='generating')setChatPhase('streaming')
        const tokenChunk=event.token;if(tokenChunk){setMessages(m=>m.map((item,i)=>i===m.length-1?{...item,content:item.content+tokenChunk}:item))}
        if(event.done){completed=true;if(event.conversation_id)setConversationId(event.conversation_id);setMessages(m=>m.map((item,i)=>i===m.length-1?{...item,sources:event.sources||[]}:item))}
        if(event.detail)throw new Error(event.detail)
      }
      while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});const blocks=buffer.split('\n\n');buffer=blocks.pop()||'';for(const block of blocks)consume(block)}
      if(buffer.trim())consume(buffer)
      if(!completed)throw new Error('AI stream ended before the response was completed')
    } catch(e) {
      const msg=e instanceof Error?e.message:'AI request failed';setMessages(m=>m.map((item,i)=>i===m.length-1?{...item,content:item.content||`I couldn't complete that request. ${msg}`}:item));setError(msg)
    } finally {setChatBusy(false)}
  }
  const submitQuestion=(question=prompt)=>{
    const q=question.trim()
    if(q.length<3||chatBusy)return
    if(!selectedRepo){
      setPrompt(q)
      setPendingQuestion(q)
      setError('')
      setActive('AI Workspace')
      return
    }
    setPendingQuestion(null)
    setActive('AI Workspace')
    void sendQuestion(q)
  }
  const updatePrompt=(value:string)=>{
    setPrompt(value)
    setPendingQuestion(current=>current?(value.trim().length>=3?value:null):null)
  }
  useEffect(()=>{
    if(!token||!selectedRepo||!pendingQuestion)return
    const question=pendingQuestion
    setPendingQuestion(null)
    setError('')
    setActive('AI Workspace')
    void sendQuestion(question,selectedRepo)
  },[token,selectedRepo,pendingQuestion])

  const connectGithub=async()=>{
    if(!token)return
    try{const data=await request<{authorization_url:string}>('/api/v1/auth/github/start',token);window.location.assign(data.authorization_url)}
    catch(e){setError(e instanceof Error?e.message:'Could not start GitHub authorization')}
  }
  const importGithub=async()=>{
    if(!token||!githubUrl.trim())return
    setGithubBusy(true);setError('')
    try{await request<Repo>('/api/v1/repositories/github',token,{method:'POST',body:JSON.stringify({url:githubUrl.trim()})});setGithubUrl('');await refreshRepos();notify('GitHub repository imported and indexed.')}
    catch(e){setError(e instanceof Error?e.message:'GitHub import failed')}finally{setGithubBusy(false)}
  }
  const exportRepository=async()=>{
    if(!token||!selectedRepo)return
    try{const response=await fetch(`${API}/api/v1/repositories/${selectedRepo}/export`,{headers:{Authorization:`Bearer ${token}`}});if(!response.ok)throw new Error('Repository export failed');const blob=await response.blob();const url=window.URL.createObjectURL(blob);const anchor=document.createElement('a');anchor.href=url;anchor.download=`${activeRepo?.name||'repository'}-repopilot.zip`;anchor.click();window.URL.revokeObjectURL(url);notify('Repository snapshot exported.')}
    catch(e){setError(e instanceof Error?e.message:'Export failed')}
  }
  const reindex=async()=>{
    if(!token||!selectedRepo)return
    try{await request(`/api/v1/repositories/${selectedRepo}/reindex`,token,{method:'POST'});notify('Re-indexing job queued. Check Agent Activity for status.')}
    catch(e){setError(e instanceof Error?e.message:'Could not queue re-indexing')}
  }
  const proposePatch=async()=>{
    if(!token||!selectedRepo||!selectedFile||patchInstruction.trim().length<5)return
    setPatchBusy(true);setError('');setPatchProposal(null)
    try{const data=await request<{id:number;diff:string;explanation:string;status:string}>('/api/v1/patches/propose',token,{method:'POST',body:JSON.stringify({repository_id:selectedRepo,file_path:selectedFile.path,instruction:patchInstruction})});setPatchProposal(data)}
    catch(e){setError(e instanceof Error?e.message:'Patch proposal failed')}finally{setPatchBusy(false)}
  }
  const generateTests=async()=>{
    if(!token||!selectedRepo||!selectedFile||!testFilePath.trim())return
    setPatchBusy(true);setError('');setPatchProposal(null)
    try{const data=await request<{id:number;diff:string;explanation:string;status:string}>('/api/v1/tests/generate',token,{method:'POST',body:JSON.stringify({repository_id:selectedRepo,source_file_path:selectedFile.path,test_file_path:testFilePath,instructions:'Generate focused unit tests for the selected source file, including normal behavior and edge cases.'})});setPatchProposal(data);notify('Test file generated. Review it before approval.')}
    catch(e){setError(e instanceof Error?e.message:'Test generation failed')}finally{setPatchBusy(false)}
  }
  const decidePatch=async(approve:boolean)=>{
    if(!token||!patchProposal)return
    setPatchBusy(true)
    try{await request(`/api/v1/patches/${patchProposal.id}/${approve?'approve':'reject'}`,token,{method:'POST'});notify(approve?'Patch approved and applied to the repository snapshot.':'Patch rejected.');if(approve)setApprovedPatchId(patchProposal.id);else setApprovedPatchId(null);setPatchProposal(null);if(approve&&selectedFile)await openFile(selectedFile.path)}
    catch(e){setError(e instanceof Error?e.message:'Patch decision failed')}finally{setPatchBusy(false)}
  }
  const publishPatch=async()=>{
    if(!token||!approvedPatchId)return
    setPatchBusy(true)
    try{const result=await request<{commit_url?:string}>(`/api/v1/patches/${approvedPatchId}/publish`,token,{method:'POST'});notify(result.commit_url?`Published to GitHub: ${result.commit_url}`:'Patch published to GitHub.');setPublishedPatchId(approvedPatchId);setApprovedPatchId(null)}
    catch(e){setError(e instanceof Error?e.message:'GitHub publish failed')}finally{setPatchBusy(false)}
  }
  const rollbackPatch=async()=>{
    if(!token||!approvedPatchId)return
    setPatchBusy(true)
    try{await request(`/api/v1/patches/${approvedPatchId}/rollback`,token,{method:'POST'});notify('Applied snapshot change rolled back.');setApprovedPatchId(null);if(selectedFile)await openFile(selectedFile.path)}
    catch(e){setError(e instanceof Error?e.message:'Patch rollback failed')}finally{setPatchBusy(false)}
  }
  const revertPublishedPatch=async()=>{
    if(!token||!publishedPatchId)return
    setPatchBusy(true)
    try{const result=await request<{commit_url?:string}>(`/api/v1/patches/${publishedPatchId}/revert-github`,token,{method:'POST'});notify(result.commit_url?`GitHub revert committed: ${result.commit_url}`:'GitHub patch reverted.');setPublishedPatchId(null);if(selectedFile)await openFile(selectedFile.path)}
    catch(e){setError(e instanceof Error?e.message:'GitHub revert failed')}finally{setPatchBusy(false)}
  }
  const runSearch=async()=>{
    if(!token||!selectedRepo||!globalQuery.trim())return
    setLoading(true);setError('')
    try{const data=await request<{results:typeof searchResults}>(`/api/v1/repositories/${selectedRepo}/search?q=${encodeURIComponent(globalQuery)}`,token);setSearchResults(data.results)}
    catch(e){setError(e instanceof Error?e.message:'Search failed')}finally{setLoading(false)}
  }
  const debugRepository=async()=>{
    if(!token||!selectedRepo||debugInput.trim().length<3)return
    setAgentBusy(true);setError('');setDebugResult('')
    try{const data=await request<{result:string}>('/api/v1/agent/investigate',token,{method:'POST',body:JSON.stringify({repository_id:selectedRepo,task:`Debug this error using repository evidence. Identify likely root cause, relevant files, and safe remediation. Do not claim tests were run.

${debugInput}`})});setDebugResult(data.result)}
    catch(e){setError(e instanceof Error?e.message:'Debugging investigation failed')}finally{setAgentBusy(false)}
  }
  const runReview=async()=>{
    if(!token||!selectedRepo)return
    setLoading(true);setReviewResult('');setError('')
    try{const data=await request<{review:string}>('/api/v1/review',token,{method:'POST',body:JSON.stringify({repository_id:selectedRepo,scope:'security, correctness, reliability, and maintainability'})});setReviewResult(data.review)}
    catch(e){setError(e instanceof Error?e.message:'Code review failed')}finally{setLoading(false)}
  }
  const runAgent=async()=>{
    if(!token||!selectedRepo||agentTask.trim().length<3)return
    setAgentBusy(true);setError('')
    try{await request('/api/v1/agent/investigate',token,{method:'POST',body:JSON.stringify({repository_id:selectedRepo,task:agentTask})});const rows=await request<typeof agentRuns>(`/api/v1/agent/executions?repository_id=${selectedRepo}`,token);setAgentRuns(rows)}
    catch(e){setError(e instanceof Error?e.message:'Investigation failed')}finally{setAgentBusy(false)}
  }
  const runPythonTests=async()=>{
    if(!token||!selectedRepo)return
    setTestBusy(true);setTestRun(null);setError('')
    try{
      const result=await request<{status:string;exit_code:number|null;output:string;duration_seconds:number;timed_out:boolean}>('/api/v1/tests/run',token,{method:'POST',body:JSON.stringify({repository_id:selectedRepo,timeout_seconds:45})})
      setTestRun(result)
      const rows=await request<typeof agentRuns>(`/api/v1/agent/executions?repository_id=${selectedRepo}`,token)
      setAgentRuns(rows)
    }catch(e){setError(e instanceof Error?e.message:'Sandbox test run failed')}finally{setTestBusy(false)}
  }
  const copyText=async(value:string)=>{
    try{await navigator.clipboard.writeText(value);notify('Copied to clipboard.')}
    catch{setError('Clipboard access is unavailable in this browser context.')}
  }
  const deleteRepo=async(id:number)=>{
    if(!token||!window.confirm('Permanently delete this repository and its indexed source?'))return
    try{await request(`/api/v1/repositories/${id}`,token,{method:'DELETE'});setMessages([]);setConversationId(null);setSelectedFile(null);await refreshRepos();notify('Repository deleted.')}catch(e){setError(e instanceof Error?e.message:'Delete failed')}
  }
  const filteredFiles=useMemo(()=>files.filter(f=>f.path.toLowerCase().includes(search.toLowerCase())),[files,search])

  if(!token) return <div className="auth-shell"><Ambient/><motion.form className="auth-card glass-card" onSubmit={submitAuth} initial={{opacity:0,y:18}} animate={{opacity:1,y:0}}><div className="brand auth-brand"><img className="brand-logo" src="/logo-dark.svg" alt="RepoPilot"/><span className="brand-version">AI</span></div><div className="eyebrow"><span className="eyebrow-line"/> REPOSITORY INTELLIGENCE</div><h1 aria-label={register?'Create your workspace.':'Welcome back.'}>{register?'Create your workspace':'Welcome back'}<span>.</span></h1><p className="auth-sub">{register?'Create a secure account to index and understand your code.':'Sign in to continue exploring your code intelligence workspace.'}</p><label>Email address<input type="email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@company.com" required autoComplete="email"/></label><label>Password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} placeholder="At least 10 characters" minLength={10} required autoComplete={register?'new-password':'current-password'}/></label>{authError&&<div className="error-banner">{authError}</div>}<button className="primary-button auth-submit" disabled={authBusy}>{authBusy?<LoaderCircle className="spin" size={17}/>:<Sparkles size={16}/>} {authBusy?'Please wait…':register?'Create account':'Sign in'}</button><button type="button" className="auth-switch" onClick={()=>{setRegister(!register);setAuthError('')}}>{register?'Already have an account? Sign in':'New to RepoPilot? Create an account'}</button><div className="auth-foot"><ShieldCheck size={13}/> Passwords are salted and hashed. Private workspace access.</div></motion.form></div>

  return <div className="app-shell"><Ambient/>
    <aside className={`sidebar ${mobileNav?'sidebar-open':''}`}><div className="brand"><img className="brand-logo" src="/logo-dark.svg" alt="RepoPilot"/><span className="brand-version">AI</span></div>
      <div className="nav-label">WORKSPACE</div><nav className="main-nav">{nav.map(item=><button key={item.label} className={`nav-item ${active===item.label?'active':''}`} onClick={()=>{setActive(item.label);setMobileNav(false)}}><item.icon size={17}/><span>{item.label}</span>{item.label==='AI Workspace'&&<i>AI</i>}{active===item.label&&<motion.div layoutId="nav-glow" className="nav-active-glow"/>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="usage-card"><div className="usage-head"><span>AI provider</span><span className="usage-period">GROQ</span></div><div className="usage-value">{activeRepo?'Repository ready':'Awaiting repository'}</div><div className="usage-track"><span style={{width:activeRepo?'100%':'0%'}}/></div><small>AI answers require a backend Groq key</small></div><button className="profile-row" onClick={logout}><div className="profile-avatar"><LogOut size={15}/></div><div className="profile-copy"><b>Sign out</b><small>{userEmail}</small></div><ChevronRight size={16}/></button></div>
    </aside>
    <main className="main-area"><header className="topbar"><div className="topbar-left"><button className="mobile-menu icon-button" onClick={()=>setMobileNav(!mobileNav)} aria-label="Toggle navigation"><Menu size={19}/></button><div className="breadcrumb">{active!=='AI Workspace'&&<><button type="button" className="breadcrumb-home" aria-label="Go to AI Workspace" onClick={()=>{setActive('AI Workspace');setMobileNav(false)}}>Workspace</button><ChevronRight size={13}/></>}<strong>{active}</strong></div></div><div className="topbar-right"><div className={`system-status ${health?.status==='ok'?'healthy':health?'degraded':healthLoaded?'unavailable':'checking'}`} aria-live="polite"><span className="status-dot"/>{health?.status==='ok'?'API connected':health?'API degraded':healthLoaded?'API unavailable':'Checking API'}</div><button className="icon-button" onClick={()=>refreshRepos()} aria-label="Refresh"><RefreshCw size={16}/></button><button className="account-button" type="button" aria-label="View account settings" title={userEmail||'Account'} onClick={()=>{setActive('Settings');setMobileNav(false)}}><span className="account-avatar" aria-hidden="true">{userEmail.slice(0,1).toUpperCase()||'A'}</span><span className="account-email">{userEmail||'Account'}</span></button></div></header>
      <div className="content-wrap"><AnimatePresence mode="wait"><motion.div key={active} initial={{opacity:0,y:9,filter:'blur(4px)'}} animate={{opacity:1,y:0,filter:'blur(0px)'}} exit={{opacity:0,y:-5}} transition={{duration:.23}}>
        <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line"/> YOUR ENGINEERING COMMAND CENTER</div><h1>{active==='Overview'?<>Build with <span>code intelligence.</span></>:active}</h1><p>{active==='Overview'?'Your codebase, understood. Your next breakthrough, closer.':`Explore ${active.toLowerCase()} across your connected repositories.`}</p></div><div className="heading-actions"><button className="secondary-button" onClick={()=>fileInput.current?.click()}><UploadCloud size={16}/> Upload ZIP</button><button className="primary-button" onClick={()=>fileInput.current?.click()}><Plus size={17}/> Add repository</button><input ref={fileInput} hidden type="file" accept=".zip,application/zip" onChange={e=>e.target.files?.[0]&&upload(e.target.files[0])}/></div></div>
        {error&&<div className="error-banner page-error"><span>{error}</span><button onClick={()=>setError('')} aria-label="Dismiss"><X size={15}/></button></div>}
        {uploading&&<div className="upload-progress"><LoaderCircle className="spin" size={16}/> Uploading, validating and indexing repository…</div>}
        {active==='Overview'&&<>
          <div className="stats-grid"><GlassCard delay={.03}><Stat icon={FolderGit2} label="Repositories" value={repos.length} tone="blue" foot="Your connected codebases"/></GlassCard><GlassCard delay={.08}><Stat icon={FileCode2} label="Indexed files" value={repos.reduce((n,r)=>n+r.file_count,0)} tone="violet" foot="Text source files"/></GlassCard><GlassCard delay={.13}><Stat icon={BrainCircuit} label="Code chunks" value={repos.reduce((n,r)=>n+r.chunk_count,0)} tone="cyan" foot="Retrieval-ready segments"/></GlassCard><GlassCard delay={.18}><Stat icon={Zap} label="AI provider" value={health===null?healthLoaded?'Unavailable':'Checking':health.ai_configured?'Configured':'Not configured'} tone="amber" foot={health?.ai_configured?'Backend provider key is configured':'Set GROQ_API_KEY to enable AI answers'}/></GlassCard></div>
          <GlassCard className="language-card"><PanelTitle icon={FileCode2} title="Language composition" subtitle={activeRepo?`Indexed files in ${activeRepo.name}`:'Select a repository to see language distribution'}/><LanguageChart files={files}/></GlassCard>
          <div className="section-row"><div><h2>Repository landscape</h2><p>Live data from your private workspace.</p></div><button className="text-action" onClick={()=>setActive('Repositories')}>All repositories <ArrowUpRight size={15}/></button></div>
          <div className="main-grid"><div className="left-stack"><GlassCard className="repo-panel"><div className="panel-heading"><div className="panel-title"><div className="panel-icon"><FolderGit2 size={17}/></div><div><h3>Your repositories</h3><p>{repos.length} connected codebase{repos.length===1?'':'s'}</p></div></div><button className="icon-button small" onClick={()=>fileInput.current?.click()} aria-label="Add repository"><Plus size={17}/></button></div>{repos.length?<RepoList repos={repos} selected={selectedRepo} onSelect={id=>{setSelectedRepo(id);setActive('Repositories')}} onDelete={deleteRepo}/>:<EmptyRepos onUpload={()=>fileInput.current?.click()}/>}</GlassCard>
          <GlassCard className="activity-panel"><div className="panel-heading"><div className="panel-title"><div className="panel-icon"><Activity size={17}/></div><div><h3>Indexing activity</h3><p>{activeRepo?'Current background job status':'Select a repository to monitor indexing'}</p></div></div><span className="live-pill"><span/> {activeRepo?'POLLING JOBS':'IDLE'}</span></div>{indexJobs.length?<div className="activity-list">{indexJobs.slice(0,5).map(job=><div className="activity-row index-activity" key={job.id}><div className="activity-symbol"><Activity size={14}/></div><div><b>{job.status}</b><p>{job.detail}</p><div className="index-track"><i style={{width:`${job.progress}%`}}/></div></div><span>{job.progress}%</span></div>)}</div>:activeRepo?<div className="activity-list"><div className="activity-row"><div className="activity-symbol"><Check size={14}/></div><div><b>{activeRepo.name}</b><p>{activeRepo.status} · {activeRepo.file_count} files · {activeRepo.chunk_count} chunks</p></div></div></div>:<div className="activity-empty"><div className="activity-symbol"><Activity size={15}/></div><div><b>No repository selected</b><p>Select a repository to see real indexing job progress.</p></div></div>}</GlassCard></div>
          <div className="right-stack"><GlassCard className="copilot-card"><div className="copilot-top"><div className="copilot-symbol"><Sparkles size={18}/></div><span className="copilot-label">REP O PILOT INTELLIGENCE</span><span className="beta-pill">RAG WORKSPACE</span></div><h3>Ask your codebase<br/><span>anything.</span></h3><p>Retrieve relevant code and receive evidence-backed answers with source citations.</p><div className="prompt-box"><textarea value={prompt} onChange={e=>updatePrompt(e.target.value)} placeholder={activeRepo?'How does authentication work?':'Select or upload a repository first'} rows={3} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();submitQuestion()}}}/><div className="prompt-bottom"><span><Command size={12}/> Enter to send · Shift+Enter for newline</span><button type="button" aria-label="Send question to AI" disabled={prompt.trim().length<3||chatBusy} onClick={()=>submitQuestion()}><Send size={17}/></button></div></div><div className="suggestion-label">SUGGESTED INVESTIGATIONS</div>{['Map the architecture and key modules','Trace the user sign-up flow','Find potential security issues'].map(q=><button className="suggestion" key={q} onClick={()=>submitQuestion(q)}><span>{q}</span><ArrowUpRight size={14}/></button>)}</GlassCard><PipelineCard/></div></div>
        </>}
        {active==='Repositories'&&<div className="repo-management"><GlassCard className="wide-panel"><PanelTitle icon={FolderGit2} title="Connected repositories" subtitle="Upload a ZIP archive or import a GitHub repository."/><RepoList repos={repos} selected={selectedRepo} onSelect={id=>setSelectedRepo(id)} onDelete={deleteRepo}/>{!repos.length&&<EmptyRepos onUpload={()=>fileInput.current?.click()}/>}<div className="github-import"><div><Github size={18}/><b>Import from GitHub</b><small>{githubConnected?'GitHub account connected. Private repository access is enabled.':'Connect your GitHub account to import private repositories securely, or paste a public repository URL.'}</small></div><div className="github-import-row"><button className="secondary-button" onClick={connectGithub}><Github size={15}/> {githubConnected?'Reconnect GitHub':'Connect GitHub'}</button><input value={githubUrl} onChange={e=>setGithubUrl(e.target.value)} placeholder="https://github.com/owner/repository"/><button className="primary-button" disabled={githubBusy||!githubUrl.trim()} onClick={importGithub}>{githubBusy?<LoaderCircle className="spin" size={15}/>:<Github size={15}/>} Import</button></div></div>{selectedRepo&&<div className="repo-actions"><button className="secondary-button" onClick={reindex}><RefreshCw size={15}/> Re-index selected repository</button><button className="secondary-button" onClick={()=>setActive('Code Explorer')}><FileCode2 size={15}/> Explore source</button><button className="secondary-button" onClick={exportRepository}><UploadCloud size={15}/> Export ZIP</button></div>}</GlassCard></div>}
        {active==='Architecture'&&<ArchitecturePage health={health} jobs={indexJobs} chatBusy={chatBusy} chatPhase={chatPhase}/>}
        {active==='Repository Details'&&<GlassCard className="section-placeholder"><div className="placeholder-icon"><FolderGit2 size={25}/></div><h2>Repository details</h2><select value={selectedRepo??''} onChange={e=>setSelectedRepo(Number(e.target.value)||null)}><option value="">Select repository</option>{repos.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select>{activeRepo?<><p>{activeRepo.source.toUpperCase()} source · {activeRepo.status} · Added {new Date(activeRepo.created_at).toLocaleString()} · Last indexed {activeRepo.last_indexed_at?new Date(activeRepo.last_indexed_at).toLocaleString():'not recorded'}</p><div className="repo-detail-grid"><div><small>Indexed files</small><b>{activeRepo.file_count}</b></div><div><small>Code chunks</small><b>{activeRepo.chunk_count}</b></div><div><small>Detected languages</small><b>{[...new Set(files.map(f=>f.language))].join(', ')||'Not available'}</b></div></div><div className="repo-actions"><button className="secondary-button" onClick={reindex}><RefreshCw size={15}/> Re-index</button><button className="secondary-button" onClick={exportRepository}><UploadCloud size={15}/> Export ZIP</button><button className="secondary-button" onClick={()=>setActive('Code Explorer')}><FileCode2 size={15}/> Browse files</button></div></>:<p>Choose one of your repositories to inspect its metadata and indexing state.</p>}</GlassCard>}
        {active==='AI Workspace'&&<div className="chat-layout"><GlassCard className="chat-main"><div className="chat-header"><div className="panel-title"><div className="copilot-symbol"><BrainCircuit size={18}/></div><div><h3>Repository intelligence</h3><p>{activeRepo?activeRepo.name:'Choose a repository to begin'}</p></div></div><select value={selectedRepo??''} onChange={e=>{setSelectedRepo(Number(e.target.value)||null);setMessages([]);setConversationId(null)}}><option value="">Select repository</option>{repos.map(r=><option value={r.id} key={r.id}>{r.name}</option>)}</select></div>{pendingQuestion&&<div className="upload-progress" role="status"><MessageSquareText size={15}/><span>Waiting for a repository. Your question will send automatically when one is selected.</span><button type="button" className="secondary-button" onClick={()=>setActive('Repositories')}>Open repositories</button></div>}<div className="chat-messages">{!messages.length&&!chatBusy&&!pendingQuestion&&<div className="chat-welcome"><div className="welcome-orb"><BrainCircuit size={28}/></div><h2>Let's understand your code.</h2><p>Ask a question about the selected repository. RepoPilot retrieves source chunks before asking the configured AI model to answer.</p><div className="prompt-chips">{['How is the project structured?','Where is authentication implemented?','Explain the main request lifecycle.'].map(q=><button key={q} onClick={()=>submitQuestion(q)}>{q}<ArrowUpRight size={13}/></button>)}</div></div>}{messages.map((m,i)=><div className={`chat-message ${m.role}`} key={i}><div className="message-avatar">{m.role==='assistant'?<Sparkles size={15}/>:<Command size={14}/>}</div><div className="message-body"><div className="message-role">{m.role==='assistant'?'REP O PILOT':'YOU'}</div><MessageContent content={m.content} onCopy={copyText}/>{m.sources && m.sources.length>0 && <div className="source-list"><div className="source-title">RETRIEVED SOURCES</div>{m.sources.map((s,j)=><button className="source-chip" key={`${s.path}-${j}`} onClick={()=>openFile(s.path,s.start_line,s.end_line)}><FileCode2 size={13}/>{s.path}<span>:{s.start_line}-{s.end_line}</span></button>)}</div>}</div></div>)}{chatBusy&&<div className="chat-message assistant"><div className="message-avatar"><Sparkles size={15}/></div><div className="message-body"><div className="message-role">{chatPhase==='retrieving'?'RETRIEVING REPOSITORY CONTEXT':'STREAMING GROUNDED RESPONSE'}</div><div className="typing-dots"><i/><i/><i/></div><small>{chatPhase==='retrieving'?'The backend is retrieving indexed source before streaming.':'Evidence-backed response tokens are arriving from the configured model.'}</small></div></div>}<div ref={chatEnd}/></div><div className="chat-composer"><textarea value={prompt} onChange={e=>updatePrompt(e.target.value)} placeholder={selectedRepo?'Ask a question about your repository…':'Select a repository first'} rows={2} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();submitQuestion()}}}/><div className="composer-bottom"><span><ShieldCheck size={12}/> Answers grounded in retrieved source · Shift+Enter for newline</span><button type="button" aria-label="Send question" disabled={prompt.trim().length<3||chatBusy} onClick={()=>submitQuestion()}><Send size={15}/></button></div></div></GlassCard><GlassCard className="context-panel"><PanelTitle icon={Network} title="Context pipeline" subtitle="Retrieval status for this workspace"/><PipelineCard compact/><div className="conversation-history"><b>Conversation history</b>{conversations.length?conversations.map(c=><button key={c.id} className={conversationId===c.id?'active':''} onClick={()=>loadConversation(c.id)}>{c.title}<small>{new Date(c.updated_at).toLocaleDateString()}</small></button>):<small>No saved conversations yet.</small>}</div><div className="context-note"><ShieldCheck size={15}/><span>Repository files are treated as untrusted data. The assistant is instructed to cite evidence and acknowledge missing context.</span></div></GlassCard></div>}
        {active==='Code Explorer'&&<div className="explorer-layout"><GlassCard className="file-panel"><PanelTitle icon={FolderGit2} title="Repository files" subtitle={`${files.length} indexed text files`}/><div className="file-search"><Search size={14}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Filter files…"/></div><FileTree files={filteredFiles} selectedPath={selectedFile?.path} onSelect={path=>openFile(path)} emptyMessage={files.length?'No files match your filter.':'Upload a repository to explore its files.'} loading={filesLoading}/></GlassCard><GlassCard className="code-panel">{selectedFile?<><div className="code-head"><div><FileCode2 size={15}/><b>{selectedFile.path}</b></div><span>{selectedFile.language}</span><button className="icon-button small" onClick={()=>copyText(selectedFile.content)} aria-label="Copy source file"><Copy size={14}/></button></div><pre className="code-view" ref={codeViewer}><code>{selectedFile.content.split('\n').map((line,i)=><span className={`code-line ${highlightRange&&i+1>=highlightRange.start&&i+1<=highlightRange.end?'citation-highlight':''}`} key={i}><i>{i+1}</i><SyntaxText text={line||' '} /></span>)}</code></pre><div className="patch-editor"><b>AI-assisted change proposal</b><textarea value={patchInstruction} onChange={e=>setPatchInstruction(e.target.value)} rows={2} placeholder="Describe the change you want. Nothing is applied until you approve it."/><button className="secondary-button" disabled={patchBusy||patchInstruction.trim().length<5} onClick={proposePatch}>{patchBusy?<LoaderCircle className="spin" size={14}/>:<Sparkles size={14}/>} Propose change</button><div className="test-generation"><input value={testFilePath} onChange={e=>setTestFilePath(e.target.value)} aria-label="Generated test file path"/><button className="secondary-button" disabled={patchBusy||!testFilePath.trim()} onClick={generateTests}><Check size={14}/> Generate unit tests</button></div>{approvedPatchId&&<div className="patch-actions">{activeRepo?.source==='github'&&<button className="secondary-button" disabled={patchBusy} onClick={publishPatch}><Github size={14}/> Publish approved change to GitHub</button>}<button className="secondary-button danger-button" disabled={patchBusy} onClick={rollbackPatch}><RefreshCw size={14}/> Roll back applied snapshot</button></div>}{publishedPatchId&&activeRepo?.source==='github'&&<button className="secondary-button danger-button" disabled={patchBusy} onClick={revertPublishedPatch}><RefreshCw size={14}/> Revert published GitHub commit</button>}{patchProposal&&<div className="patch-preview"><b>Proposed diff · pending approval</b><p>{patchProposal.explanation}</p><pre>{patchProposal.diff}</pre><div><button className="secondary-button" disabled={patchBusy} onClick={()=>decidePatch(false)}>Reject</button><button className="primary-button" disabled={patchBusy} onClick={()=>decidePatch(true)}>Approve and apply</button></div></div>}</div></>:<div className="code-empty"><FileText size={28}/><h3>Select a source file</h3><p>Choose a file from the explorer to inspect its contents and line numbers.</p></div>}</GlassCard></div>}
        {active==='Search'&&<GlassCard className="section-placeholder"><div className="placeholder-icon"><Search size={25}/></div><h2>Search your codebase</h2><p>Search indexed repository chunks using lexical matching with semantic ranking when embeddings are available.</p><select value={selectedRepo??''} onChange={e=>setSelectedRepo(Number(e.target.value)||null)}><option value="">Select repository</option>{repos.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select><div className="github-import-row"><input value={globalQuery} onChange={e=>setGlobalQuery(e.target.value)} placeholder="Search symbols, modules, config, behavior…" onKeyDown={e=>e.key==='Enter'&&runSearch()}/><button className="primary-button" disabled={!selectedRepo||loading||!globalQuery.trim()} onClick={runSearch}><Search size={15}/> Search</button></div>{searchResults.map((r,i)=><button className="search-result" key={`${r.path}-${r.start_line}-${i}`} onClick={()=>openFile(r.path,r.start_line,r.end_line)}><b>{r.path}:{r.start_line}-{r.end_line}</b><small>{r.language} · relevance {r.score.toFixed(3)}</small><pre>{r.content}</pre></button>)}</GlassCard>}
        {active==='Debugging'&&<GlassCard className="section-placeholder"><div className="placeholder-icon"><Zap size={25}/></div><h2>AI debugging workbench</h2><p>Paste an error message or stack trace. RepoPilot retrieves relevant repository code and proposes a cited diagnosis. It does not execute untrusted code.</p><select value={selectedRepo??''} onChange={e=>setSelectedRepo(Number(e.target.value)||null)}><option value="">Select repository</option>{repos.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select><textarea value={debugInput} onChange={e=>setDebugInput(e.target.value)} rows={7} placeholder="Paste stack trace, error message, or unexpected behavior…"/><button className="primary-button" disabled={!selectedRepo||agentBusy||debugInput.trim().length<3} onClick={debugRepository}>{agentBusy?<LoaderCircle className="spin" size={15}/>:<Zap size={15}/>} Analyze error</button>{debugResult&&<div className="workflow-result"><h3>Evidence-backed diagnosis</h3><pre>{debugResult}</pre></div>}</GlassCard>}
        {active==='Code Review'&&<GlassCard className="section-placeholder"><div className="placeholder-icon"><ShieldCheck size={25}/></div><h2>Evidence-first code review</h2><p>Review uses retrieved repository evidence. It does not claim to run external scanners or tests.</p><select value={selectedRepo??''} onChange={e=>setSelectedRepo(Number(e.target.value)||null)}><option value="">Select repository</option>{repos.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select><button className="primary-button" disabled={!selectedRepo||loading} onClick={runReview}><Sparkles size={15}/> {loading?'Reviewing evidence…':'Run code review'}</button>{reviewResult&&<div className="workflow-result"><h3>Review findings</h3><pre>{reviewResult}</pre></div>}</GlassCard>}
        {active==='Agent Activity'&&<div className="agent-workspace"><GlassCard className="section-placeholder"><div className="placeholder-icon"><Activity size={25}/></div><h2>Repository investigation agent</h2><p>Bounded, read-only investigation: retrieve evidence, inspect indexed symbols, and synthesize cited findings. No arbitrary shell commands are executed.</p><select value={selectedRepo??''} onChange={e=>setSelectedRepo(Number(e.target.value)||null)}><option value="">Select repository</option>{repos.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select><textarea value={agentTask} onChange={e=>setAgentTask(e.target.value)} rows={3}/><button className="primary-button" disabled={!selectedRepo||agentBusy} onClick={runAgent}>{agentBusy?<LoaderCircle className="spin" size={15}/>:<BrainCircuit size={15}/>} {agentBusy?'Investigating…':'Run investigation'}</button><div className="sandbox-action"><b>Isolated Python test run</b><p>Runs the indexed snapshot in a disposable, network-disabled container. No source changes are applied.</p><button className="secondary-button" disabled={!selectedRepo||testBusy} onClick={runPythonTests}>{testBusy?<LoaderCircle className="spin" size={14}/>:<Zap size={14}/>} {testBusy?'Running in sandbox…':'Run Python tests'}</button>{testRun&&<div className={`sandbox-result ${testRun.status}`}><div><b>{testRun.status.replace('_',' ')}</b><small>{testRun.duration_seconds}s · exit {testRun.exit_code??'—'}</small></div><pre>{testRun.output||'No test output was produced.'}</pre></div>}</div></GlassCard><GlassCard className="wide-panel"><PanelTitle icon={Activity} title="Indexing jobs" subtitle="Actual background worker status"/>{indexJobs.map(job=><div className="index-job" key={job.id}><div><b>{job.status}</b><small>{job.detail}</small></div><strong>{job.progress}%</strong><div className="index-track"><i style={{width:`${job.progress}%`}}/></div></div>)}<PanelTitle icon={Activity} title="Recorded investigations" subtitle="Persisted agent execution history"/>{agentRuns.length?agentRuns.map(run=><div className="agent-run" key={run.id}><div><b>{run.task}</b><small>{run.status} · {new Date(run.created_at).toLocaleString()}</small></div><pre>{run.result}</pre></div>):<p className="muted-empty">Run an investigation to create the first activity record.</p>}</GlassCard></div>}
        {active==='Settings'&&<div className="settings-layout"><GlassCard className="section-placeholder"><div className="placeholder-icon"><Settings2 size={25}/></div><h2>Workspace settings</h2><p>Signed in as {userEmail}. Configure Groq, GitHub OAuth, webhook, database, and sandbox secrets in the backend environment; credentials are never sent to the browser.</p><button className="secondary-button" onClick={()=>window.open(`${API}/docs`,'_blank')}>Open API documentation <ArrowUpRight size={14}/></button></GlassCard><GlassCard className="wide-panel"><PanelTitle icon={ShieldCheck} title="Security and workflow history" subtitle="Your recent account and repository events"/>{auditEvents.length?auditEvents.map(event=><div className="audit-event" key={event.id}><div><b>{event.action.split('.').join(' · ')}</b><small>{new Date(event.created_at).toLocaleString()}</small></div><span className={`audit-status ${event.status}`}>{event.status}</span>{typeof event.details?.path==='string'&&<small>{event.details.path}</small>}</div>):<p className="muted-empty">No audit events have been recorded yet.</p>}</GlassCard></div>}
      </motion.div></AnimatePresence><footer className="footer"><span>© 2026 RepoPilot <span className="footer-dot">·</span> Intelligence for every line.</span><span><span className="footer-dot"/> PRIVATE WORKSPACE <span className="footer-dot">·</span> <ShieldCheck size={12}/> Evidence-first AI</span></footer></div>
    </main><AnimatePresence>{toast&&<motion.div className="toast" initial={{opacity:0,y:12}} animate={{opacity:1,y:0}} exit={{opacity:0,y:8}}><Check size={15}/>{toast}</motion.div>}</AnimatePresence>
  </div>
}
function SyntaxText({text}:{text:string}){
  const pattern=/(\/\/.*|#.*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\b(?:const|let|var|function|class|def|return|import|from|async|await|if|else|for|while|try|except|catch|new|export|default|public|private|static|true|false|null|None|True|False|interface|type|extends|implements|throw|raise|yield|with|as|in|pass|self)\b|\b\d+(?:\.\d+)?\b)/g
  const nodes:ReactNode[]=[];let cursor=0;let match:RegExpExecArray|null;let key=0
  while((match=pattern.exec(text))!==null){if(match.index>cursor)nodes.push(text.slice(cursor,match.index));const token=match[0];const cls=token.startsWith('//')||token.startsWith('#')?'syntax-comment':token.startsWith('"')||token.startsWith("'")||token.startsWith('`')?'syntax-string':/^\d/.test(token)?'syntax-number':'syntax-keyword';nodes.push(<span className={cls} key={key++}>{token}</span>);cursor=pattern.lastIndex}
  if(cursor<text.length)nodes.push(text.slice(cursor))
  return <>{nodes}</>
}

function LanguageChart({files}:{files:RepoFile[]}){
  const counts=files.reduce<Record<string,number>>((all,file)=>{all[file.language]=(all[file.language]||0)+1;return all},{})
  const rows=Object.entries(counts).sort((a,b)=>b[1]-a[1]).slice(0,7)
  const max=Math.max(1,...rows.map(row=>row[1]))
  return <div className="language-chart">{rows.length?rows.map(([name,count],i)=><div className="language-row" key={name}><span>{name}</span><div><motion.i initial={{width:0}} animate={{width:`${count/max*100}%`}} transition={{duration:.65,delay:i*.06,ease:'easeOut'}}/></div><b>{count}</b></div>):<p className="muted-empty">No indexed language data yet. Import a repository to populate this chart.</p>}</div>
}

function renderInlineText(text:string,keyPrefix:string):ReactNode[]{
  const nodes:ReactNode[]=[]
  const pattern=/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]\n]+:\d+(?:-\d+)?\])/g
  let cursor=0;let match:RegExpExecArray|null;let index=0
  while((match=pattern.exec(text))!==null){
    if(match.index>cursor)nodes.push(text.slice(cursor,match.index))
    const token=match[0]
    const key=`${keyPrefix}-${index++}`
    if(token.startsWith('**')){
      nodes.push(<strong key={key}>{renderInlineText(token.slice(2,-2),key)}</strong>)
    }else if(token.startsWith('`')){
      nodes.push(<code className="message-inline-code" key={key}>{token.slice(1,-1)}</code>)
    }else{
      const citation=/^\[(.+):(\d+)(?:-(\d+))?\]$/.exec(token)
      if(citation){
        const path=citation[1]
        const start=Number(citation[2])
        const end=Number(citation[3]||citation[2])
        nodes.push(<span className="inline-citation" key={key} title={`${path}:${start}-${end}`}>{path}:{start}{end===start?'':`-${end}`}</span>)
      }else{
        nodes.push(token)
      }
    }
    cursor=pattern.lastIndex
  }
  if(cursor<text.length)nodes.push(text.slice(cursor))
  return nodes
}

function renderMarkdownBlocks(text:string,keyPrefix:string):ReactNode[]{
  const blocks:ReactNode[]=[]
  let paragraph:string[]=[]
  let listItems:string[]=[]
  let orderedList=false
  let key=0
  const flushParagraph=()=>{
    if(!paragraph.length)return
    const content=paragraph.join('\n')
    blocks.push(<p key={`${keyPrefix}-paragraph-${key}`}>{renderInlineText(content,`${keyPrefix}-paragraph-${key++}`)}</p>)
    paragraph=[]
  }
  const flushList=()=>{
    if(!listItems.length)return
    const List=orderedList?'ol':'ul'
    blocks.push(<List key={`${keyPrefix}-list-${key}`}>{listItems.map((item,index)=><li key={`${keyPrefix}-list-${key}-${index}`}>{renderInlineText(item,`${keyPrefix}-list-${key}-${index}`)}</li>)}</List>)
    listItems=[]
    key++
  }
  for(const line of text.split(/\r?\n/)){
    const item=/^\s*(?:([-+*])|(\d+[.)]))\s+(.+)$/.exec(line)
    if(item){
      flushParagraph()
      const nextOrdered=Boolean(item[2])
      if(listItems.length&&orderedList!==nextOrdered)flushList()
      orderedList=nextOrdered
      listItems.push(item[3])
    }else if(!line.trim()){
      flushParagraph()
      flushList()
    }else{
      flushList()
      paragraph.push(line)
    }
  }
  flushParagraph()
  flushList()
  return blocks.length?blocks:[<p key={`${keyPrefix}-empty`}>{text}</p>]
}

function MessageContent({content,onCopy}:{content:string;onCopy:(value:string)=>void}){
  const blocks:ReactNode[]=[]
  const pattern=/```([\w+-]*)\n([\s\S]*?)```/g
  let cursor=0;let match:RegExpExecArray|null;let key=0
  while((match=pattern.exec(content))!==null){
    const code=match[2];const language=match[1]||'CODE'
    const before=content.slice(cursor,match.index)
    if(before.trim())blocks.push(...renderMarkdownBlocks(before,`text-${key++}`))
    const codeLines=code.split('\n')
    blocks.push(<motion.div key={`code-${key++}`} className="message-code" initial={{opacity:0,y:6}} animate={{opacity:1,y:0}}><div><span>{language}</span><button onClick={()=>onCopy(code)}><Copy size={12}/> Copy</button></div><pre><code>{codeLines.map((line,i)=><span className="highlighted-code-line" key={i}><SyntaxText text={line}/>{i<codeLines.length-1?'\n':''}</span>)}</code></pre></motion.div>)
    cursor=pattern.lastIndex
  }
  const tail=content.slice(cursor)
  if(tail.trim())blocks.push(...renderMarkdownBlocks(tail,`text-${key++}`))
  if(!blocks.length)blocks.push(<p key="empty">{content}</p>)
  return <div className="message-content">{blocks}</div>
}

function ArchitecturePage({health,jobs,chatBusy,chatPhase}:{health:Health|null;jobs:IndexJob[];chatBusy:boolean;chatPhase:'retrieving'|'streaming'}){
  const [selected,setSelected]=useState(0)
  const activeJob=jobs.find(job=>['queued','running'].includes(job.status.toLowerCase()))
  const latestJob=jobs[0]
  const jobStatus=activeJob?`${activeJob.status} · ${activeJob.progress}%`:latestJob?`${latestJob.status} · ${latestJob.progress}%`:'No recent indexing job'
  const retrievalStatus=chatBusy&&chatPhase==='retrieving'?'Retrieving repository context':health?.vector_store||'Checking'
  const generationStatus=chatBusy&&chatPhase==='streaming'?'Streaming response':health?.ai_configured?'Ready when requested':'Provider not configured'
  const stages=[
    {name:'Repository files',detail:'ZIP and GitHub archive ingestion validates paths, filters secrets and binaries, identifies languages, and preserves source locations.',status:jobStatus},
    {name:'Syntax parsing',detail:'Python uses the built-in AST parser. Other supported languages use Tree-sitter to extract functions, classes, methods and source ranges.',status:activeJob?.detail||(health?.tree_sitter_installed?'Tree-sitter available':'Parser unavailable')},
    {name:'Embeddings',detail:'all-MiniLM-L6-v2 generates normalized 384-dimensional vectors. Semantic indexing is available only when the optional model is installed and loaded.',status:health?.embeddings_installed?'Embedding package installed':'Lexical fallback'},
    {name:'Vector + keyword retrieval',detail:'pgvector similarity and lexical ranking are fused with reciprocal-rank fusion. SQLite development mode uses lexical retrieval unless embeddings are available for in-process ranking.',status:retrievalStatus},
    {name:'Reranking',detail:'An optional CrossEncoder can rerank the fused candidate set. It is disabled by default and requires the model to be installed.',status:health?.reranker_enabled?'Enabled':'Optional / disabled'},
    {name:'LLM reasoning',detail:'Groq receives a bounded evidence context. Repository content is treated as untrusted data and answers must cite source paths and line ranges.',status:generationStatus},
    {name:'Evidence answer',detail:'The assistant streams response tokens and returns the retrieved source references. When evidence is missing, it says so rather than inventing code.',status:chatBusy&&chatPhase==='streaming'?'Response streaming':'SSE + citations'}
  ]
  return <div className="architecture-page">
    <GlassCard className="wide-panel">
      <PanelTitle icon={Network} title="Retrieval architecture" subtitle="Select a stage to inspect its real responsibility and current configuration"/>
      <div className="architecture-flow">{stages.map((stage,i)=><button key={stage.name} className={`architecture-node ${selected===i?'selected':''}`} onClick={()=>setSelected(i)}><span>{String(i+1).padStart(2,'0')}</span><b>{stage.name}</b><small>{stage.status}</small></button>)}</div>
      <div className="architecture-detail"><div className="eyebrow">PIPELINE STAGE {selected+1} / {stages.length}</div><h3>{stages[selected].name}</h3><p>{stages[selected].detail}</p><span className="live-pill">{stages[selected].status}</span></div>
    </GlassCard>
    <GlassCard className="wide-panel">
      <PanelTitle icon={Activity} title="Current processing" subtitle="Live chat stages and persisted indexing job progress"/>
      <div className="current-processing" aria-live="polite">
        <div><small>Repository indexing</small><b>{jobStatus}</b><span>{activeJob?.detail||latestJob?.detail||'No recent job reported by the backend.'}</span>{latestJob&&<div className="index-track"><i style={{width:`${latestJob.progress}%`}}/></div>}</div>
        <div><small>AI request</small><b>{chatBusy?chatPhase==='retrieving'?'Retrieving source':'Streaming response':'Idle'}</b><span>{chatBusy?chatPhase==='retrieving'?'The backend is retrieving indexed repository context.':'Answer tokens are streaming from the configured provider.':'No chat request is currently running.'}</span></div>
      </div>
    </GlassCard>
    <GlassCard className="wide-panel">
      <PanelTitle icon={Activity} title="Service readiness" subtitle="Reported by the backend health endpoint"/>
      <div className="service-grid">{[['API',health?.status||'unknown'],['Database',health?.database||'unknown'],['Redis',health?.redis||'unknown'],['Vector store',health?.vector_store||'unknown'],['Groq',health?.ai_configured?'configured':'not configured'],['GitHub OAuth',health?.github_oauth_configured?'configured':'not configured']].map(([name,value])=><div key={name}><small>{name}</small><b>{value}</b></div>)}</div>
    </GlassCard>
  </div>
}
function Ambient(){return <><div className="pointer-glow" aria-hidden="true"/><div className="ambient ambient-one"/><div className="ambient ambient-two"/><div className="ambient ambient-three"/><div className="grid-overlay"/><svg className="neural-network" viewBox="0 0 1200 800" preserveAspectRatio="none" aria-hidden="true"><path d="M40 190 210 260 360 130 520 230 690 120 840 250 1030 150 1170 220M100 560 270 460 430 600 580 430 740 570 900 440 1080 570M210 260 270 460M360 130 430 600M520 230 580 430M690 120 740 570M840 250 900 440M1030 150 1080 570" /><circle cx="210" cy="260" r="3"/><circle cx="360" cy="130" r="3"/><circle cx="520" cy="230" r="3"/><circle cx="690" cy="120" r="3"/><circle cx="840" cy="250" r="3"/><circle cx="1030" cy="150" r="3"/><circle cx="270" cy="460" r="3"/><circle cx="430" cy="600" r="3"/><circle cx="580" cy="430" r="3"/><circle cx="740" cy="570" r="3"/><circle cx="900" cy="440" r="3"/><circle cx="1080" cy="570" r="3"/></svg><div className="particle-field" aria-hidden="true">{Array.from({length:18},(_,i)=><i key={i} style={{left:`${(i*47)%100}%`,top:`${(i*31)%100}%`,animationDelay:`${(i%7)*-1.7}s`}}/>)}</div></>}
function Stat({icon:Icon,label,value,tone,foot}:{icon:typeof FolderGit2;label:string;value:string|number;tone:string;foot:string}){
  const reduce=useReducedMotion()
  const numberValue=typeof value==='number'?value:null
  const counter=useMotionValue(numberValue===null||reduce?numberValue??0:0)
  const [count,setCount]=useState(counter.get())
  useMotionValueEvent(counter,'change',latest=>setCount(Math.round(latest)))
  useEffect(()=>{
    if(numberValue===null)return
    if(reduce){counter.set(numberValue);return}
    const controls=animate(counter,numberValue,{duration:.7,ease:'easeOut'})
    return controls.stop
  },[counter,numberValue,reduce])
  const display=numberValue===null?value:count
  return <><div className="stat-top"><span>{label}</span><div className={`stat-icon ${tone}`}><Icon size={17}/></div></div><motion.div key={String(value)} className={`stat-number ${typeof value==='string'?'stat-word':''}`} initial={reduce?false:{opacity:0,y:8,scale:.96}} animate={{opacity:1,y:0,scale:1}} transition={{duration:reduce?0:.38,ease:'easeOut'}}>{display}</motion.div><div className="stat-foot"><span className="stat-neutral">{foot}</span><span className="stat-caption">CURRENT</span></div></>
}
function PanelTitle({icon:Icon,title,subtitle}:{icon:typeof FolderGit2;title:string;subtitle:string}){return <div className="panel-heading"><div className="panel-title"><div className="panel-icon"><Icon size={17}/></div><div><h3>{title}</h3><p>{subtitle}</p></div></div></div>}
function RepoList({repos,selected,onSelect,onDelete}:{repos:Repo[];selected:number|null;onSelect:(id:number)=>void;onDelete:(id:number)=>void}){return <div className="repo-list">{repos.map(r=><div className={`repo-item ${selected===r.id?'repo-selected':''}`} key={r.id}><button className="repo-main" onClick={()=>onSelect(r.id)}><div className="repo-avatar"><FolderGit2 size={17}/></div><div><b>{r.name}</b><small>{r.source.toUpperCase()} · {r.file_count} files · {r.chunk_count} chunks</small></div></button><span className="repo-state"><i/>{r.status}</span><button className="icon-button small danger-button" onClick={()=>onDelete(r.id)} title="Delete repository" aria-label={`Delete ${r.name}`}><Trash2 size={14}/></button></div>)}</div>}
type FileDirectory={name:string;path:string;directories:Map<string,FileDirectory>;files:RepoFile[]}
export function FileTree({files,selectedPath,onSelect,emptyMessage,loading=false}:{files:RepoFile[];selectedPath?:string;onSelect:(path:string)=>void;emptyMessage:string;loading?:boolean}){
  const root=useMemo(()=>{
    const directory:FileDirectory={name:'',path:'',directories:new Map(),files:[]}
    for(const file of files){
      const parts=file.path.split('/').filter(Boolean)
      let current=directory
      parts.forEach((part,index)=>{
        if(index===parts.length-1){current.files.push(file);return}
        let child=current.directories.get(part)
        if(!child){child={name:part,path:current.path?`${current.path}/${part}`:part,directories:new Map(),files:[]};current.directories.set(part,child)}
        current=child
      })
    }
    return directory
  },[files])
  if(loading)return <div className="file-list file-skeletons" aria-label="Loading repository files" aria-busy="true">{Array.from({length:6},(_,index)=><span key={index} className="file-skeleton"/>)}</div>
  if(!files.length)return <div className="file-list"><p className="muted-empty">{emptyMessage}</p></div>
  return <div className="file-list file-tree" role="tree" aria-label="Repository file tree">
    {[...root.directories.values()].map(directory=><FileTreeDirectory key={directory.path} directory={directory} depth={0} selectedPath={selectedPath} onSelect={onSelect}/>)}
    {root.files.map(file=><FileTreeLeaf key={file.id} file={file} depth={0} selected={selectedPath===file.path} onSelect={onSelect}/>)}
  </div>
}
function FileTreeDirectory({directory,depth,selectedPath,onSelect}:{directory:FileDirectory;depth:number;selectedPath?:string;onSelect:(path:string)=>void}){
  const [expanded,setExpanded]=useState(depth===0)
  const reduce=useReducedMotion()
  return <div className="file-tree-branch">
    <button role="treeitem" className="folder-row" style={{paddingLeft:`${8+depth*14}px`}} aria-expanded={expanded} onClick={()=>setExpanded(open=>!open)}><ChevronRight size={13} className={expanded?'tree-chevron expanded':''}/><FolderGit2 size={14}/><span>{directory.name}</span></button>
    <AnimatePresence initial={false}>{expanded&&<motion.div key="children" role="group" className="file-tree-children" initial={reduce?false:{height:0,opacity:0}} animate={{height:'auto',opacity:1}} exit={{height:0,opacity:0}} transition={{duration:reduce?0:.18}}>{[...directory.directories.values()].map(child=><FileTreeDirectory key={child.path} directory={child} depth={depth+1} selectedPath={selectedPath} onSelect={onSelect}/>)}
      {directory.files.map(file=><FileTreeLeaf key={file.id} file={file} depth={depth+1} selected={selectedPath===file.path} onSelect={onSelect}/>)}</motion.div>}
    </AnimatePresence>
  </div>
}
function FileTreeLeaf({file,depth,selected,onSelect}:{file:RepoFile;depth:number;selected:boolean;onSelect:(path:string)=>void}){
  const name=file.path.split('/').pop()||file.path
  return <button role="treeitem" title={file.path} className={`file-row ${selected?'selected':''}`} style={{paddingLeft:`${22+depth*14}px`}} onClick={()=>onSelect(file.path)}><FileCode2 size={14}/><span>{name}</span><small>{file.language}</small></button>
}
function EmptyRepos({onUpload}:{onUpload:()=>void}){return <div className="empty-repos"><div className="empty-orbit"><div className="orbit-ring ring-a"/><div className="orbit-ring ring-b"/><div className="orbit-core"><FolderGit2 size={24}/></div><span className="orbit-node node-a"/><span className="orbit-node node-b"/><span className="orbit-node node-c"/></div><h3>Your code universe starts here</h3><p>Upload a ZIP archive. RepoPilot validates the archive, filters secrets and binary files, then indexes source into line-aware retrieval chunks.</p><button className="primary-button" onClick={onUpload}><UploadCloud size={16}/> Upload your first repository</button><div className="empty-support"><span><Check size={12}/> Private by account</span><span><Check size={12}/> Source citations</span><span><Check size={12}/> Safe ZIP extraction</span></div></div>}
function PipelineCard({compact=false}:{compact?:boolean}){const steps=[['Source files',FolderGit2],['Parse & chunk',FileCode2],['Hybrid retrieval',Network],['Groq reasoning',BrainCircuit],['Evidence answer',Sparkles]] as const;return <div className={`pipeline-card ${compact?'pipeline-compact':''}`}><div className="pipeline-heading"><div><h3>Intelligence pipeline</h3><p>Retrieval-augmented generation</p></div><div className="pipeline-status"><span/> PIPELINE OVERVIEW</div></div><div className="pipeline-flow">{steps.map(([name,Icon],i)=><div key={name}><div className="pipeline-step"><div className="pipeline-step-icon"><Icon size={15}/></div><span>{name}</span></div>{i<steps.length-1&&<div className="pipeline-connector"><i/></div>}</div>)}</div><div className="pipeline-foot"><span>Semantic + lexical when local embeddings are enabled; lexical fallback otherwise</span><span>RERANKER OPTIONAL</span></div></div>}
export default App
