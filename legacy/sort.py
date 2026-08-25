import os
import shutil
import re  # 정규 표현식을 사용하기 위한 도구
from pathlib import Path

# 1. 경로 설정

## target_path = str(Path.home() / "CrossDevice" / "내휴대폰" / "storage" / "DCIM" / "Camera")
# ── 경로 설정 · 여기만 바꾸면 된다 ─────────────────────────────
# PC 를 옮겨도 돌아가게 홈 폴더 기준으로 잡는다(Path.home()).
# 다른 곳을 쓰려면 아래 줄의 값을 바꾼다.  예) str(Path(r'D:\정리할폴더'))
target_path = str(Path.home() / "Downloads" / "a")

def organize_photos(path):
    if not os.path.exists(path):
        print("⚠️ 경로를 찾을 수 없습니다.")
        return

    os.chdir(path)
    
    skipped_files = []
    success_count = 0
    not_found_year = [] # 연도를 찾지 못한 파일들

    print(f"✅ 작업 시작: {path}\n" + "-"*40)

    for filename in os.listdir('.'):
        if os.path.isfile(filename):
            # [핵심] 파일명에서 4자리 숫자(1900~2099년 사이)를 찾습니다.
            # \d{4}는 숫자 4개를 의미합니다.
            match = re.search(r'(19|20)\d{2}', filename)
            
            if match:
                year = match.group() # 찾아낸 연도 (예: 2020)
                
                if not os.path.exists(year):
                    os.makedirs(year)
                
                destination = os.path.join(year, filename)

                if os.path.exists(destination):
                    skipped_files.append(f"{filename} (이미 {year} 폴더에 있음)")
                    continue
                
                try:
                    shutil.move(filename, destination)
                    print(f"🚚 이동 완료: {filename} -> {year}/")
                    success_count += 1
                except Exception as e:
                    print(f"❌ 오류 발생: {e}")
            else:
                # 연도 패턴이 없는 파일은 따로 기록
                not_found_year.append(filename)

    # --- 최종 결과 보고 ---
    print("-" * 40)
    print(f"📊 작업 결과 보고")
    print(f"✔️ 이동 성공: {success_count}개")
    
    if skipped_files:
        print(f"⚠️ 중복/건너뜀: {len(skipped_files)}개")
        for f in skipped_files:
            print(f"   └ {f}")
            
    if not_found_year:
        print(f"❓ 연도를 찾지 못한 파일: {len(not_found_year)}개 (이동 안 함)")
        for f in not_found_year:
            print(f"   └ {f}")

organize_photos(target_path)