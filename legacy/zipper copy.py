import os
import zipfile
from pathlib import Path

# 1. 설정
# ── 경로 설정 · 여기만 바꾸면 된다 ─────────────────────────────
# PC 를 옮겨도 돌아가게 홈 폴더 기준으로 잡는다(Path.home()).
# 다른 곳을 쓰려면 아래 줄의 값을 바꾼다.  예) str(Path(r'D:\정리할폴더'))
zip_folder_path = str(Path.home() / "Downloads") # zip 파일들이 모여있는 폴더
extract_to_path = str(Path.home() / "Downloads" / "a")    # 하나로 합쳐질 대상 폴더

def extract_and_delete_originals(src_path, dest_path):
    if not os.path.exists(dest_path):
        os.makedirs(dest_path, exist_ok=True)

    print(f"📦 압축 해제 및 원본 삭제 시작: {dest_path}")
    print("-" * 50)

    zip_files = [f for f in os.listdir(src_path) if f.lower().endswith('.zip')]
    
    if not zip_files:
        print("ℹ️ 처리할 .zip 파일이 없습니다.")
        return

    for filename in zip_files:
        zip_file_full_path = os.path.join(src_path, filename)
        
        try:
            # 1. 압축 해제 작업 시작
            with zipfile.ZipFile(zip_file_full_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    filename_only = os.path.basename(member)
                    
                    if filename_only:  # 디렉토리가 아닌 파일인 경우만
                        target_file_path = os.path.join(dest_path, filename_only)
                        
                        # 중복 파일명 처리 (번호 붙이기)
                        name, ext = os.path.splitext(filename_only)
                        count = 1
                        while os.path.exists(target_file_path):
                            target_file_path = os.path.join(dest_path, f"{name}_({count}){ext}")
                            count += 1
                        
                        # 데이터 쓰기
                        with open(target_file_path, "wb") as f:
                            f.write(zip_ref.read(member))
            
            # 2. 압축 해제가 성공적으로 끝나면 원본 파일 삭제
            os.remove(zip_file_full_path)
            print(f"🔥 해제 완료 및 삭제됨: {filename}")
            
        except Exception as e:
            print(f"❌ 에러 발생({filename}): {e}")
            print(f"⚠️ 안전을 위해 {filename} 원본은 삭제하지 않았습니다.")

    print("-" * 50)
    print("✨ 모든 작업이 완료되었습니다.")

extract_and_delete_originals(zip_folder_path, extract_to_path)