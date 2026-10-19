# 인스타툰 자동화

> 현재 저장 구조는 v2입니다. series.json·episode.json에 정보를 통합하고 history.jsonl에 이력을 누적합니다. 상세 API와 이전 방식은 [데이터 계약](references/contracts.md)과 [tool 문서](references/tools.md)를 따릅니다. 아래 과거 파일 분리 설계보다 v2 계약을 우선합니다.

인스타툰의 기획부터 대본, 컷 구성, 이미지 제작, 게시물 준비까지 반복 작업을 자동화하기 위한 프로젝트입니다.

7개 제작 스킬과 공통 ref, 로컬 상태 저장·한글 합성·미리보기·승인 기록·PNG 출력 tool을 구현했습니다. 검색·이미지 생성 어댑터는 아직 연결하지 않았습니다.

## 시작하기

이 저장소에서 “직장인의 월요일을 주제로 인스타툰 제작해줘”처럼 요청합니다. [AGENTS.md](AGENTS.md)가 제작 의도를 인식해 [PROMPT.md](PROMPT.md), [전체 진행 스킬](skills/instatoon/SKILL.md), 필요한 전문 스킬 순서로 연결합니다.

스타일·캐릭터는 에이전트가 제안하고 제작합니다. 현재 사용 가능한 기능과 미구현 범위는 [tool 현황](references/tools.md), 전체 구조는 [설계 문서](docs/architecture.md)를 참고합니다.

## 로컬 tool 실행

Python 3.11 이상과 macOS 또는 Linux에서 실행합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m tools.instatoon --help
.venv/bin/python -m pytest -q
```

한글 합성 샘플은 다음 명령으로 만듭니다. 다른 운영체제에서는 실제 한글 폰트 경로를 지정합니다.

```bash
.venv/bin/python -m examples.render_demo --font /System/Library/Fonts/AppleSDGothicNeo.ttc
```

`outputs/lettering-demo/preview/preview.png`에 도형 기반 식자 샘플을 생성합니다. 실제 에피소드 승인이나 게시는 수행하지 않습니다. 입력 JSON과 명령별 사용법은 [tool 문서](references/tools.md)에 있습니다.

## 목표 제작 흐름

1. 주제와 타깃 독자를 정하고 에피소드 아이디어를 만든다.
2. 대본을 작성하고 컷별 장면, 대사, 내레이션으로 나눈다.
3. 캐릭터와 화풍 설정에 맞춰 컷 이미지를 제작한다.
4. 말풍선과 텍스트를 배치하고 게시용 이미지를 내보낸다.
5. 최종 검수와 사용자 승인 후 1920·1080 PNG를 출력한다.
6. 게시 연동과 댓글 분석은 후속 범위로 둔다.

## 개발 시작점

- 먼저 [개발 로드맵](docs/roadmap.md)의 초기 결정 사항을 정합니다.
- 로컬 tool은 Python·Pillow·fontTools를 사용하며, 이미지 생성 서비스는 별도로 연결합니다.
- API 키와 액세스 토큰은 코드에 넣지 않고 환경변수로 관리합니다.
- 생성 결과물은 기본적으로 Git에서 제외되는 `outputs/` 폴더에 저장합니다.

## 폴더 구조

```text
instatoon-automation/
├── AGENTS.md
├── PROMPT.md
├── skills/       # 전체 진행과 전문 스킬 7개
├── references/   # 제작 기준과 공통 계약 10개
├── tools/        # 상태·식자·출력 CLI
├── tests/        # 실패 처리와 제작 흐름 검증
├── examples/     # 식자 샘플 실행
└── docs/         # 설계와 원본 제작 자료
```
