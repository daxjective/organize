import os
import zipfile
from pathlib import Path

# 1. 설정
# ── 경로 설정 · 여기만 바꾸면 된다 ─────────────────────────────
# PC 를 옮겨도 돌아가게 홈 폴더 기준으로 잡는다(Path.home()).
# 다른 곳을 쓰려면 아래 줄의 값을 바꾼다.  예) str(Path(r'D:\정리할폴더'))
zip_folder_path = str(Path.home() / "Downloads") # zip 파일들이 모여있는 폴더
extract_to_path = str(Path.home() / "Downloads" / "a")    # 압축을 풀어서 모을 폴더

def extract_all_to_one_folder(src_path, dest_path):
    if not os.path.exists(dest_path):
        os.makedirs(dest_path, exist_ok=True)

    print(f"📂 압축 해제 시작: {dest_path} 로 모으는 중...")
    print("-" * 50)

    # 폴더 내 모든 파일 확인
    for filename in os.listdir(src_path):
        if filename.lower().endswith('.zip'):
            zip_file_full_path = os.path.join(src_path, filename)
            
            with zipfile.ZipFile(zip_file_full_path, 'r') as zip_ref:
                # 압축 파일 내부의 각 파일들에 대하여
                for member in zip_ref.namelist():
                    # 폴더 구조는 무시하고 파일명만 추출 (경로 제외)
                    filename_only = os.path.basename(member)
                    
                    # 폴더 형태가 아닌 실제 파일인 경우에만 진행
                    if filename_only:
                        target_path = os.path.join(dest_path, filename_only)
                        
                        # --- [중복 처리] 같은 이름이 있으면 번호 붙이기 ---
                        name, ext = os.path.splitext(filename_only)
                        count = 1
                        while os.path.exists(target_path):
                            target_path = os.path.join(dest_path, f"{name}_({count}){ext}")
                            count += 1
                        
                        # 파일 쓰기 (압축 해제)
                        with open(target_path, "wb") as f:
                            f.write(zip_ref.read(member))
                
                print(f"✅ 완료: {filename}")

    print("-" * 50)
    print(f"✨ 모든 압축 파일이 {dest_path} 폴더로 합쳐졌습니다.")

extract_all_to_one_folder(zip_folder_path, extract_to_path)