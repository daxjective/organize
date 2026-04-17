import os
import shutil
import re
# 0. F드라이브로는 액세스가 거부됨 
# 1. 설정 (경로 뒤에 r을 꼭 붙여주세요)
source_path = r'C:\Users\notebiz765\CrossDevice\davin의 S23 Ultra\storage\DCIM\Camera'
base_destination = r'F:\day'

def organize_across_drives(src, dest_root):
    # 목적지 폴더가 없으면 생성
    if not os.path.exists(dest_root):
        os.makedirs(dest_root)
        print(f"📂 목적지 루트 생성: {dest_root}")

    skipped_files = []
    success_count = 0
    error_files = []

    print(f"🚀 드라이브 간 이동 시작: {src} -> {dest_root}")
    print("-" * 50)

    # 원본 경로 존재 확인
    if not os.path.exists(src):
        print("⚠️ 원본 경로를 찾을 수 없습니다. 스마트폰 연결 상태를 확인하세요.")
        return

    for filename in os.listdir(src):
        full_src_path = os.path.join(src, filename)
        
        if os.path.isfile(full_src_path):
            # 연도 패턴 찾기
            match = re.search(r'(19|20)\d{2}', filename)
            
            if match:
                year = match.group()
                target_dir = os.path.join(dest_root, year)
                
                if not os.path.exists(target_dir):
                    os.makedirs(target_dir)
                
                final_dest_path = os.path.join(target_dir, filename)

                # 중복 확인
                if os.path.exists(final_dest_path):
                    skipped_files.append(filename)
                    continue
                
                try:
                    # [변경] move 대신 copy2(메타데이터 포함 복사) 사용
                    shutil.copy2(full_src_path, final_dest_path)
                    
                    # 복사가 성공했다면 원본 삭제 (이게 더 안전합니다)
                    os.remove(full_src_path)
                    
                    print(f"✅ 이동 완료: {filename} -> {year}/")
                    success_count += 1
                except Exception as e:
                    error_files.append(f"{filename} (사유: {e})")
            else:
                pass # 연도 없는 파일은 무시

    # 최종 보고
    print("-" * 50)
    print(f"📊 결과 요약")
    print(f"✔️ 성공: {success_count}개")
    print(f"⚠️ 중복 건너뜀: {len(skipped_files)}개")
    if error_files:
        print(f"❌ 오류 발생: {len(error_files)}개")
        for err in error_files:
            print(f"   └ {err}")

organize_across_drives(source_path, base_destination)