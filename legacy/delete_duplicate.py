import os
import hashlib

# 1. 정리할 폴더 경로
target_path = r'C:\Users\notebiz765\Downloads\a'

def get_file_hash(file_path):
    """파일의 지문(MD5 해시)을 생성합니다."""
    hasher = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except:
        return None

def clean_duplicates(path):
    if not os.path.exists(path):
        print(f"⚠️ 경로를 찾을 수 없습니다: {path}")
        return

    hashes = {}  # {해시값: 최초발견_파일경로}
    dup_count = 0

    print(f"🔍 중복 파일 검사 및 삭제 시작: {path}")
    print("-" * 50)

    # os.walk(topdown=False)를 써서 하위 폴더 파일부터 검사합니다.
    for root, dirs, files in os.walk(path, topdown=False):
        for filename in files:
            full_path = os.path.join(root, filename)
            
            # 파일 지문 확인
            f_hash = get_file_hash(full_path)
            if not f_hash: continue

            if f_hash in hashes:
                # 이미 동일한 내용의 파일이 다른 곳에 존재함
                print(f"🗑️ 중복 삭제: {full_path}")
                os.remove(full_path)
                dup_count += 1
            else:
                # 처음 발견된 고유한 파일
                hashes[f_hash] = full_path

    print("-" * 50)
    print(f"📊 정리 완료! 총 {dup_count}개의 중복 파일을 삭제했습니다.")

clean_duplicates(target_path)