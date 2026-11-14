import io, zipfile
from fastapi import UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.core.database import Base
from app.models import User, RepositoryFile, CodeChunk
from app.ingestion.zip_ingest import ingest_zip

def make_zip(entries):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as z:
        for name,content in entries.items(): z.writestr(name,content)
    buffer.seek(0)
    return buffer

def test_zip_ingestion_filters_secrets_and_preserves_line_numbers():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user=User(email='test@example.com',password_hash='x');db.add(user);db.commit()
        upload=UploadFile(filename='sample.zip',file=make_zip({'sample/src/auth.py':'def login():\n    return True\n','sample/.env':'SECRET=abc','sample/node_modules/pkg/index.js':'bad'}))
        repo=ingest_zip(upload,user.id,db,1024*1024)
        assert repo.file_count==1 and repo.chunk_count==1
        file=db.scalar(select(RepositoryFile).where(RepositoryFile.repository_id==repo.id))
        chunk=db.scalar(select(CodeChunk).where(CodeChunk.repository_id==repo.id))
        assert file.path=='sample/src/auth.py'
        assert chunk.start_line==1 and chunk.end_line==2
    Base.metadata.drop_all(engine)

def test_zip_ingestion_rejects_path_traversal():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user=User(email='test2@example.com',password_hash='x');db.add(user);db.commit()
        upload=UploadFile(filename='bad.zip',file=make_zip({'../escape.py':'print(1)'}))
        from fastapi import HTTPException
        try: ingest_zip(upload,user.id,db,1024*1024)
        except HTTPException as exc: assert exc.status_code==400
        else: raise AssertionError('Unsafe archive should not be ingested')
    Base.metadata.drop_all(engine)

def test_long_single_line_is_split_into_bounded_chunks():
    from app.ingestion.zip_ingest import _line_chunks, MAX_CHUNK_CHARS
    chunks=list(_line_chunks(['x'*(MAX_CHUNK_CHARS+100)]))
    assert len(chunks)==2
    assert all(len(content)<=MAX_CHUNK_CHARS for content,_,_ in chunks)
    assert all(start==1 and end==1 for _,start,end in chunks)


def test_zip_ingestion_filters_known_secret_patterns():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user=User(email='secret-filter@example.com',password_hash='x');db.add(user);db.commit()
        upload=UploadFile(filename='sample.zip',file=make_zip({
            'sample/src/app.py':'def hello():\n    return "safe"\n',
            'sample/config/credentials.py':'AWS_SECRET_ACCESS_KEY = "' + ('A'*40) + '"\n'
        }))
        repo=ingest_zip(upload,user.id,db,1024*1024)
        paths=[f.path for f in db.scalars(select(RepositoryFile).where(RepositoryFile.repository_id==repo.id)).all()]
        assert paths == ['sample/src/app.py']
    Base.metadata.drop_all(engine)


def test_ingest_zip_replaces_existing_repository_snapshot_atomically():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user=User(email='replace@example.com',password_hash='x');db.add(user);db.commit()
        first=UploadFile(filename='demo.zip',file=make_zip({'demo/old.py':'def old(): return 1\n'}))
        repo=ingest_zip(first,user.id,db,1024*1024,source='github')
        second=UploadFile(filename='demo.zip',file=make_zip({'demo/new.py':'def new(): return 2\n'}))
        updated=ingest_zip(second,user.id,db,1024*1024,source='github',existing_repo=repo)
        paths=[f.path for f in db.scalars(select(RepositoryFile).where(RepositoryFile.repository_id==repo.id)).all()]
        assert updated.id==repo.id and paths==['demo/new.py']
        assert updated.file_count==1 and updated.chunk_count==1
    Base.metadata.drop_all(engine)
