import os
import hashlib
import re

# 1. 정리할 폴더 경로
target_path = r'C:\Users\notebiz765\Downloads\a'

def get_file_hash(file_path):
    """파일의 데이터 지문을 생성합니다."""
    hasher = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except:
        return None

def clean_strict_duplicates(path):
    if not os.path.exists(path):
        print(f"⚠️ 경로를 찾을 수 없습니다: {path}")
        return

    # {(파일크기, 해시값): '원본파일경로'} 형태로 저장하여 중복 판단
    seen_files = {} 
    deleted_count = 0

    print(f"🔍 [크기+내용] 정밀 중복 제거 시작: {path}")
    print("-" * 50)

    for root, dirs, files in os.walk(path):
        for filename in files:
            full_path = os.path.join(root, filename)
            
            try:
                # 1. 파일 크기 확인 (바이트 단위)
                file_size = os.path.getsize(full_path)
                
                # 2. 파일 데이터 지문(해시) 확인
                file_hash = get_file_hash(full_path)
                if not file_hash: continue

                # (파일크기, 해시값)이라는 고유 키 생성
                file_signature = (file_size, file_hash)

                # 3. 중복 판단
                if file_signature in seen_files:
                    # 크기와 내용이 모두 일치하는 파일이 이미 존재함
                    # 특히 파일명에 (1), _1 등이 포함되어 있다면 전형적인 복사본
                    print(f"🗑️ [중복 삭제] {filename} (크기: {file_size:,} bytes)")
                    os.remove(full_path)
                    deleted_count += 1
                else:
                    # 처음 발견된 고유 파일이면 등록
                    seen_files[file_signature] = full_path
                    
            except Exception as e:
                print(f"❌ 에러 발생({filename}): {e}")

    print("-" * 50)
    print(f"📊 정리 완료! 총 {deleted_count}개의 중복 파일을 삭제했습니다.")

clean_strict_duplicates(target_path)