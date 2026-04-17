import os
import shutil
import re

# [설정] 원본 사진이 있는 곳
source_path = r'C:\Users\notebiz765\CrossDevice\davin의 S23 Ultra\storage\DCIM\Camera'

# [설정] 정리된 폴더들이 들어갈 새 위치 (예: 내 PC의 사진 폴더)
base_destination = r'C:\Users\notebiz765\Pictures\Sorted_Photos'

def organize_to_new_location(src, dest_root):
    # 목적지 루트 폴더가 없으면 생성
    if not os.path.exists(dest_root):
        os.makedirs(dest_root)
        print(f"📂 목적지 루트 폴더 생성됨: {dest_root}")

    skipped_files = []
    success_count = 0

    print(f"🚀 분류 시작: {src} -> {dest_root}")
    print("-" * 50)

    for filename in os.listdir(src):
        full_file_path = os.path.join(src, filename)
        
        # 파일인 경우에만 진행
        if os.path.isfile(full_file_path):
            # 파일명에서 연도 4자리 추출
            match = re.search(r'(19|20)\d{2}', filename)
            
            if match:
                year = match.group()
                # 목적지 폴더 경로 설정 (예: C:\...\Sorted_Photos\2022)
                target_dir = os.path.join(dest_root, year)
                
                # 폴더가 이미 있으면 그대로 쓰고, 없으면 생성 (이게 가장 빠름)
                if not os.path.exists(target_dir):
                    os.makedirs(target_dir)
                
                final_destination = os.path.join(target_dir, filename)

                # 파일 이름 중복 체크
                if os.path.exists(final_destination):
                    skipped_files.append(f"[중복] {filename}")
                    continue
                
                try:
                    # 다른 드라이브/장치 간 이동은 move가 내부적으로 copy + delete로 동작함
                    shutil.move(full_file_path, final_destination)
                    print(f"✅ 이동: {filename} -> {year} 폴더")
                    success_count += 1
                except Exception as e:
                    print(f"❌ 에러({filename}): {e}")

    # 최종 보고
    print("-" * 50)
    print(f"📊 최종 결과: {success_count}개 이동 완료 / {len(skipped_files)}개 건너뜀")
    if skipped_files:
        print("⚠️ 건너뛴 파일 목록은 로그를 확인하세요.")

organize_to_new_location(source_path, base_destination)