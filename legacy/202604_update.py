import os
import shutil
import re

# 1. 사진이 들어있는 폴더 경로 (여기 안에 폴더들이 생깁니다)
target_path = r'C:\Users\notebiz765\Downloads\a' 

def organize_fast(path):
    if not os.path.exists(path):
        print(f"⚠️ 경로를 찾을 수 없습니다: {path}")
        return

    # 분류할 확장자 정의
    image_exts = ('.jpg', '.jpeg', '.png', '.gif', '.heic', '.webp', '.bmp')
    video_exts = ('.mp4', '.mov', '.avi', '.mkv', '.wmv')

    success_count = 0
    skipped_count = 0

    print(f"🚀 동일 드라이브 고속 분류 시작: {path}")
    print("-" * 50)

    # os.walk로 하위 폴더까지 싹 뒤지기
    for root, dirs, files in os.walk(path):
        # 이미 분류되어 만들어진 '연도_사진/영상' 폴더 안은 건드리지 않도록 방어
        if "_사진" in root or "_영상" in root:
            continue

        for filename in files:
            full_src_path = os.path.join(root, filename)
            
            # 파일명에서 연도 추출
            match = re.search(r'(19|20)\d{2}', filename)
            
            if match:
                year = match.group()
                ext = os.path.splitext(filename)[1].lower()

                # 폴더명 결정
                if ext in image_exts:
                    folder_name = f"{year}_사진"
                elif ext in video_exts:
                    folder_name = f"{year}_영상"
                else:
                    continue

                # 목적지 폴더 생성 (target_path 바로 아래에 생성)
                dest_dir = os.path.join(path, folder_name)
                os.makedirs(dest_dir, exist_ok=True)
                
                final_dest_path = os.path.join(dest_dir, filename)

                # 파일 이동
                if not os.path.exists(final_dest_path):
                    try:
                        shutil.move(full_src_path, final_dest_path)
                        print(f"⚡ [이동] {filename} -> {folder_name}/")
                        success_count += 1
                    except Exception as e:
                        print(f"❌ [에러] {filename}: {e}")
                else:
                    skipped_count += 1

    print("-" * 50)
    print(f"📊 완료! 이동: {success_count}개 / 중복 건너뜀: {skipped_count}개")

organize_fast(target_path)