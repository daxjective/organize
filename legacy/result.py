import os
import shutil
import re
import hashlib
from pathlib import Path

# [설정] 경로를 본인 환경에 맞게 최종 확인하세요
# ── 경로 설정 · 여기만 바꾸면 된다 ─────────────────────────────
# PC 를 옮겨도 돌아가게 홈 폴더 기준으로 잡는다(Path.home()).
# 다른 곳을 쓰려면 아래 줄의 값을 바꾼다.  예) str(Path(r'D:\정리할폴더'))
source_path = str(Path.home() / "Downloads" / "a")
base_destination = r'F:\day'

def get_file_hash(file_path):
    """파일의 지문(MD5)을 추출합니다."""
    hasher = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except:
        return None

def organize_and_clean():
    if not os.path.exists(base_destination):
        os.makedirs(base_destination, exist_ok=True)

    image_exts = ('.jpg', '.jpeg', '.png', '.gif', '.heic', '.webp')
    video_exts = ('.mp4', '.mov', '.avi', '.mkv')

    # 중복 체크를 위한 셋 (크기, 해시)
    seen_files = set() 
    success_count = 0
    dup_count = 0

    print(f"🚀 작업을 시작합니다: {source_path} -> {base_destination}")
    print("-" * 60)

    # 1. 목적지(F드라이브)에 이미 있는 파일들 지문 먼저 따기 (이미 옮긴 파일과 중복 방지)
    print("🔍 목적지 폴더의 기존 파일 분석 중...")
    for root, _, files in os.walk(base_destination):
        for f in files:
            fp = os.path.join(root, f)
            f_size = os.path.getsize(fp)
            f_hash = get_file_hash(fp)
            if f_hash:
                seen_files.add((f_size, f_hash))

    # 2. 원본 폴더(Downloads\a) 순회
    for root, _, files in os.walk(source_path):
        for filename in files:
            full_src_path = os.path.join(root, filename)
            
            # 파일 크기 및 해시 추출
            f_size = os.path.getsize(full_src_path)
            f_hash = get_file_hash(full_src_path)
            if not f_hash: continue

            # [중복 체크] 내용이 이미 존재하면 원본 삭제
            # if (f_size, f_hash) in seen_files:
            #     print(f"🗑️ 중복 제거: {filename}")
            #     os.remove(full_src_path)
            #     dup_count += 1
            #     continue

            # [분류 로직] 연도 및 형식 찾기
            match = re.search(r'(19|20)\d{2}', filename)
            if match:
                year = match.group()
                ext = os.path.splitext(filename)[1].lower()

                if ext in image_exts:
                    sub_folder = f"{year}_사진"
                elif ext in video_exts:
                    sub_folder = f"{year}_영상"
                else:
                    sub_folder = f"{year}_기타"

                target_dir = os.path.join(base_destination, sub_folder)
                os.makedirs(target_dir, exist_ok=True)
                
                # 파일명 중복 처리 (내용은 다른데 이름만 같은 경우)
                final_dest_path = os.path.join(target_dir, filename)
                name, fext = os.path.splitext(filename)
                count = 1
                while os.path.exists(final_dest_path):
                    final_dest_path = os.path.join(target_dir, f"{name}_({count}){fext}")
                    count += 1

                try:
                    # 다른 드라이브이므로 복사 후 삭제(이동)
                    shutil.copy2(full_src_path, final_dest_path)
                    os.remove(full_src_path)
                    print(f"✅ 이동 완료: {filename} -> {sub_folder}/")
                    seen_files.add((f_size, f_hash))
                    success_count += 1
                except Exception as e:
                    print(f"❌ 오류 발생({filename}): {e}")

    print("-" * 60)
    print(f"📊 최종 보고")
    print(f"✔️ 안전하게 이동됨: {success_count}개")
    # print(f"🗑️ 내용 중복으로 삭제됨: {dup_count}개")
    print(f"✨ 작업이 끝났습니다!")

if __name__ == "__main__":
    organize_and_clean()