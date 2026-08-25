import os
import zipfile
import hashlib
from pathlib import Path

# 1. 설정
# ── 경로 설정 · 여기만 바꾸면 된다 ─────────────────────────────
# PC 를 옮겨도 돌아가게 홈 폴더 기준으로 잡는다(Path.home()).
# 다른 곳을 쓰려면 아래 줄의 값을 바꾼다.  예) str(Path(r'D:\정리할폴더'))
zip_folder_path = str(Path.home() / "Downloads")
extract_to_path = str(Path.home() / "Downloads" / "a")

def get_data_hash(data):
    """메모리 상의 데이터 지문(MD5)을 생성합니다."""
    return hashlib.md5(data).hexdigest()

def extract_clean_and_delete(src_path, dest_path):
    if not os.path.exists(dest_path):
        os.makedirs(dest_path, exist_ok=True)

    # 이미 목적지에 있는 파일들의 해시값을 먼저 수집 (기존 중복 방지)
    existing_hashes = set()
    print("🔍 기존 파일 분석 중...")
    for root, dirs, files in os.walk(dest_path):
        for f in files:
            full_p = os.path.join(root, f)
            try:
                with open(full_p, 'rb') as f_obj:
                    existing_hashes.add(hashlib.md5(f_obj.read()).hexdigest())
            except: continue

    print(f"📦 압축 해제 및 중복 제거 시작: {dest_path}")
    print("-" * 50)

    zip_files = [f for f in os.listdir(src_path) if f.lower().endswith('.zip')]
    
    for filename in zip_files:
        zip_file_full_path = os.path.join(src_path, filename)
        try:
            with zipfile.ZipFile(zip_file_full_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    filename_only = os.path.basename(member)
                    if not filename_only: continue

                    # 압축 파일 내 데이터를 메모리에 잠시 로드
                    file_data = zip_ref.read(member)
                    file_hash = get_data_hash(file_data)

                    # [핵심] 중복 체크: 이미 있는 내용이면 건너뜀
                    if file_hash in existing_hashes:
                        print(f"⏭️ 중복 건너뜀: {filename_only} (이미 동일 내용 존재)")
                        continue
                    
                    # 중복이 아니면 저장
                    target_file_path = os.path.join(dest_path, filename_only)
                    
                    # 파일명 중복 처리 (내용은 다른데 이름만 같은 경우)
                    name, ext = os.path.splitext(filename_only)
                    count = 1
                    while os.path.exists(target_file_path):
                        target_file_path = os.path.join(dest_path, f"{name}_({count}){ext}")
                        count += 1
                    
                    with open(target_file_path, "wb") as f:
                        f.write(file_data)
                    
                    existing_hashes.add(file_hash)
            
            # 압축 해제 성공 시 원본 zip 삭제
            os.remove(zip_file_full_path)
            print(f"🔥 처리 완료 및 원본 삭제: {filename}")
            
        except Exception as e:
            print(f"❌ 에러 발생({filename}): {e}")

    print("-" * 50)
    print("✨ 모든 중복이 제거된 상태로 합쳐졌습니다!")

extract_clean_and_delete(zip_folder_path, extract_to_path)