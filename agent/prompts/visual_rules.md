## AI 영상·이미지 생성 프롬프트 규칙
(OSideMedia/higgsfield-ai-prompt-skill, MIT 의 MCSLA 공식·카메라 용어·네거티브 지침을 요약·번안. Higgsfield·Kling·Seedance·Wan·LTX 등 어느 생성기에나 쓴다)

**쓰는 순서** — 영문 한 문단, 40~120단어(200단어 이하)
`피사체(누가·무엇 + 외형) → 행동(동사 1개 + 강도 부사) → Camera: 이름 붙은 무빙 1개 → 장소·시간대 → Look: 조명·색감·렌즈`
- 장면(컷)당 **주 행동 1개**(보조 1~2개까지), **카메라 무빙 1개**. 반대 무빙을 섞지 않는다(Dolly In + Dolly Out).
- **이미지→영상(I2V)** 은 첫 프레임에 이미 보이는 것을 다시 쓰지 않는다 — "무엇이 움직이는지"와 카메라만.
- 인물을 여러 컷에 이어 쓰면 **외형 블록**(얼굴·헤어·의상·색 — 정적 묘사만)과 **움직임 블록**(동작·카메라만)을 나눠 적는다.
- 비율·길이·해상도는 본문이 아니라 생성기 설정에 둔다(릴스 9:16). 본문에는 프레이밍을 말로: "waist-up medium shot".
- 빠른 동작이 뭉개지면 slow motion으로 만들고 편집에서 배속한다.

**막연한 말 대신 구체적인 말**
| 쓰지 말 것 | 대신 |
|---|---|
| beautiful, stunning, amazing, high quality, 4K | 지운다 — 무엇이 눈에 띄는지 장면으로 |
| cinematic, cinematic lighting | 조명·렌즈 이름: "golden-hour backlight, long shadows", "35mm, shallow depth of field" |
| dynamic, energetic | 동작·무빙으로: "whip pan", "handheld", "leaves swirl across the frame" |
| epic | "towering", "sweeping wide shot" |
| "역동적인 장면" 같은 분위기어 | 물리적 결과: "steam rises from the pot, wind lifts the tent flap" |

- **하지 말 것 대신 원하는 것**을 쓴다(네거티브 입력이 없는 모델이 많다): "no shaky camera" → "locked-off tripod shot",
  "no blur" → "subject in sharp focus, background soft bokeh". 네거티브 칸이 있는 생성기에만 별도로 네거티브를 준다.

**릴스 구간별 카메라 사전**
| 구간 | 추천 무빙 (프롬프트에 이름 그대로) |
|---|---|
| 0~3초 훅 | Crash Zoom In, Super Dolly In, Whip Pan |
| 문제·정보 전달 | static locked-off medium shot, Overhead(음식·책상·준비물), Lazy Susan(제품 한 바퀴) |
| 장소 소개 | Crane Down, Dolly Out, Hyperlapse, Timelapse Landscape |
| 감정·몰입 | slow Dolly In, Handheld, Arc |
| 장면 전환 | Whip Pan, Through Object In, match cut |
| 결과·변화 | Dolly Out reveal, Crane Up |
| 리액션·코미디 | static locked-off (카메라를 멈춰야 타이밍이 산다) |

샷 크기: extreme close-up / close-up / medium / medium full / wide / extreme wide. 앵글: eye level / low angle / high angle / overhead / Dutch angle.

**안전·권리** — 실존 인물·브랜드 로고·방송 화면을 재현하지 않는다. 이미지 안 글자는 `no text, no logo`로 막고 문구는 편집에서 얹는다.
'피해야 할 행동' 이슈는 안전한 모습(올바른 방법)을 보여 준다.
