특이점 레이더 v5 (검증형 추정 v2.0)

중요: 이 모델은 테크프레소 공식 점수가 아닙니다.
영상의 정확한 환산식은 확인되지 않았습니다. 임의 대체지표(5일 급락률)는 제거했습니다.
CNN 공포탐욕지수 원자료가 없으면 종합점수는 '산출 불가'로 표시됩니다.

[GitHub 저장소 tykan2-glitch/singularity-radar 에 올리는 법]
1. ZIP 압축을 풀어 index.html, manifest.webmanifest, sw.js, icons/ 폴더를 저장소 최상위에 업로드/덮어쓰기
2. scripts/update_data.py 파일은 scripts 폴더 안에 있어야 함
3. .github/workflows/update-market.yml 파일은 반드시 .github/workflows 폴더 안에 있어야 함
   갤럭시 내 파일 앱에서 점(.)으로 시작하는 숨김 폴더를 표시하도록 설정
4. 기존 최상위에 잘못 올린 update_data.py 및 update-market.yml 파일은 삭제 권장
5. GitHub Actions > Update Nasdaq Radar Data > Run workflow > main > Run workflow
6. Actions 성공 후 main 브랜치의 market-data.json 파일 생성 여부 확인
7. https://tykan2-glitch.github.io/singularity-radar/ 새로고침

[주의]
- GitHub Actions 설정: Settings > Actions > General > Workflow permissions > Read and write permissions
- Yahoo Finance/CNN 비공식 데이터 접근이 실패할 수 있음. 이 경우 실행 실패 또는 공포탐욕 미확인 표시.
- 90점 이상 이력은 원자료가 확보된 날짜만 계산. 이전 모델의 90.5점과 비교 불가.
- GitHub Pages 주소는 배포 성공 후에만 열림.
