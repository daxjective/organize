import os

# 현재 작업 중인 경로
#target_path = r'C:\Users\notebiz765\Downloads\a' 

print(f"🔍 탐색 시작: {target_path}")
print("-" * 50)

found = False
for root, dirs, files in os.walk(target_path):
    # 폴더명에 '사진'이나 '영상'이 포함된 폴더가 있는지 확인
    if "_사진" in root or "_영상" in root:
        print(f"📍 찾았습니다! 폴더 위치: {root}")
        print(f"   ㄴ 들어있는 파일 개수: {len(files)}개")
        found = True

if not found:
    print("❌ 이 폴더 안에는 '연도_사진/영상' 폴더가 전혀 없습니다.")
    print("   혹시 바탕화면에 '바탕화면'이라는 이름의 폴더가 새로 생기지 않았는지 확인해보세요!")