"""Build lettering test fixtures, never generate or approve a production episode.

Run from the repository: python -m examples.render_demo --font /path/to/font.ttf
"""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw
from tools.instatoon.common import Workspace, require, write_json
from tools.instatoon.render import render_panel, build_preview
from tools.instatoon.state import save_revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", required=True, help="Korean font path; not redistributed")
    parser.add_argument("--root", default=".")
    parser.add_argument("--series", default="lettering-demo")
    args = parser.parse_args()
    ws = Workspace(args.root)
    from tools.instatoon.common import identifier
    series = identifier(args.series)
    destination = ws.output(f"outputs/{series}")
    require(not destination.exists(), "Demo already exists; use a different --series")
    destination.mkdir(parents=True)
    panels, outputs, previews = [], [], []
    for index, text in enumerate(("분명 주말이었는데…\n커피부터 마시자.", "한 잔 마셨으니\n이제 시작해 볼까?"), 1):
        pid = f"panel-{index:03d}"
        # Geometric test artwork makes protected-region checks visible.
        art = Image.new("RGB", (1920, 1920), "#f5f1e8")
        draw = ImageDraw.Draw(art)
        draw.rounded_rectangle((170, 980, 1750, 1570), radius=22, fill="#d5c5a9")
        draw.ellipse((1180, 650, 1630, 1100), fill="#697d71")
        draw.rounded_rectangle((700, 1050, 950, 1350), radius=35, fill="#fffdf5", outline="#514c42", width=10)
        art_path = destination / f"{pid}-art.png"
        art.save(art_path)
        panel = {"panel_id": pid,"order":index,"purpose":"식자 기능 검증용 도형",
                 "characters":["fixture"],"action":"테스트 도형 배치","expression":"해당 없음",
                 "composition":"왼쪽 위 말풍선과 오른쪽 보호 영역","background":{"mode":"minimal","details":[]},
                 "texts":[{"text_id":f"text-{index:03d}","kind":"dialogue","speaker_id":"fixture","text":text,"reading_order":1}]}
        layout = {"schema_version":1,"panel_id":pid,"canvas":{"width":1920,"height":1920},
                  "protected_regions":[{"x":1180,"y":650,"width":450,"height":450}],
                  "items":[{"text_id":f"text-{index:03d}","reading_order":1,
                            "box":{"x":150,"y":200,"width":1050,"height":400},
                            "tail":{"x":1270,"y":680},"font_path":str(Path(args.font).resolve()),
                            "font_size":76,"line_height":112,"padding":38}],
                  "disclosure":{"text":"AI 합성 도구 검증용 샘플","box":{"x":1120,"y":1760,"width":650,"height":100},
                                "font_path":str(Path(args.font).resolve()),"font_size":34,"padding":14,"stroke_width":0}}
        req={"panel":panel,"art":ws.artifact(art_path,"art"),"layout":layout,
             "output_dir":f"outputs/{series}/renders/{pid}"}
        rendered=render_panel(ws,req)
        panels.append(panel)
        outputs.append({"panel_id":pid,"order":index,**rendered["report"]["outputs"],"render_report":rendered["report"]})
        previews.append({"panel_id":pid,"order":index,"image":rendered["report"]["outputs"]["1080"]})
    result=build_preview(ws,{"panels":previews,"output_dir":f"outputs/{series}/preview"})
    save_revision(ws,{"series_id":series,"episode_id":"sample","expected_revision":None,
                      "documents":{"storyboard":{"schema_version":1,"panels":panels}},
                      "state":{"phase":"lettering","status":"ready","ordered_panels":outputs,
                               "generation_provenance":[{"tool":"Pillow geometric fixture","purpose":"lettering test only"}],
                               "next_action":"시각 QA 후 새 revision에 final_qa를 연결한다. 실제 사용자 승인은 아직 없다."}})
    print(ws.path(result["artifacts"][0]["path"]))


if __name__ == "__main__":
    main()
