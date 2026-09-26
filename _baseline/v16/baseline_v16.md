# v1.6 行为基线快照（t8 预采 · 唯一真值）

- 采集时间：2026-09-26 11:06 – 11:10（本机 Win10/11 桌面会话，Python 3.12.10 / Pillow 12.3.0 / tk 8.6）
- 采集人：verifier（t8，attempt 1）
- 用途：t5 对照「v2 改动后行为是否与 v1.6 一致」的唯一真值；以及「真实用户数据是否被测试污染」的指纹
- 采集方式：**全部只读**；6 个回归脚本跑在 `git archive HEAD` 的纯净检出里，不在工作树跑（理由见 §0）

---

## 0. 真值口径（关键，先读这条）

**v1.6 真值 = git HEAD `541a2e4bb82aca35a2f1edaffed5dd2c34098a32`**（"v1.6: 移除「整体模糊」…"）。

采集时工作树**已不是 v1.6**——③ 配色注入的实现已在工作树里，尚未提交：

| 时刻 | `rime_char_overlay.py` 字节数 | mtime | 说明 |
|---|---|---|---|
| v1.6 提交（HEAD，LF 原样） | 168451 | — | blob sha256 `5603958E…F1737` |
| 本会话开始 | 172220（CRLF 工作副本） | 2026-09-10 22:36:20 | = HEAD 内容 + 行尾转换 |
| 采集途中 | 205859 | 2026-09-26 11:06:54 | 队友开发中（`git diff --stat` = +753 行） |
| 采集途中（再测） | 214709 | 2026-09-26 11:08:22 | 仍在变化 |
| 基线归档时（交付时刻） | — | 2026-09-26 11:13 | `git diff --stat` 已涨到 **+953 行**，工作树仍非 v1.6（开发在持续推进） |

`git diff --stat`：`rime_char_overlay.py | 753 ++++++++++`，新增顶层符号含 `extract_scheme_theme` / `build_scheme_fields` / `merge_scheme_into_yaml` / `plan_scheme_injection` / `apply_scheme_injection` / `restore_weasel_backup` / `find_weasel_deployer` / `run_weasel_deployer` / `load_scheme_manifest` 等（HEAD 版本里**没有**这些）。

→ 因此基线在纯净检出里采集，**证明老行为一致必须用 HEAD 版源码，不能用工作树**。

纯净检出重建（t5 复跑用）：

```powershell
$tmp = Join-Path $env:TEMP "rime_v16_baseline"
git archive --format=zip -o "$env:TEMP\v16_head.zip" HEAD
Expand-Archive "$env:TEMP\v16_head.zip" -DestinationPath $tmp -Force
Copy-Item .\char.png $tmp -Force                    # 夹具不入 git，需手动带
Copy-Item .\rime_char_overlay.py.bak-d $tmp -Force  # 对照版本，不入 git
python .\_baseline\v16\_run_baseline.py $tmp .\_baseline\v16
```

（`git archive` 会按本仓库配置做 LF→CRLF 转换：blob 168451 B → 检出 172220 B，
即工作树在队友动手前的原始形态；脚本运行的即这份源码。）

---

## 1. 回归基线（6 个脚本 · 全绿）

命令：`python _baseline/v16/_run_baseline.py <纯净检出> _baseline/v16`
cwd = `C:\Users\Misaka\AppData\Local\Temp\rime_v16_baseline`

| 脚本 | 退出码 | 耗时 | 断言结果 | 存档 |
|---|---|---|---|---|
| B_test_follow_sim.py | 0 | 1.6 s | `ALL CHECKS PASS`（首贴/移动×5/心跳隐藏/pinned/SHOW 自愈/CPU 采样） | `B_test_follow_sim.py.txt` |
| B_test_layer_sim.py | 0 | 3.5 s | `ALL CHECKS PASS (共 41 项断言通过)` | `B_test_layer_sim.py.txt` |
| B_test_misdetect_regress.py | 0 | 0.4 s | `=== 13/13 通过 ===` | `B_test_misdetect_regress.py.txt` |
| B_test_anim_sim.py | 0 | 0.9 s | `通过 16 项 / 失败 0 项` → `ALL CHECKS PASS` | `B_test_anim_sim.py.txt` |
| B_test_fixes.py | 0 | 9.5 s | `通过 16 项 / 失败 0 项` → `ALL CHECKS PASS` | `B_test_fixes.py.txt` |
| B_test_extras.py | 0 | 3.1 s | `通过 54 项 / 失败 0 项` → `ALL CHECKS PASS` | `B_test_extras.py.txt` |

合计 **156+ 项断言 / 0 失败**（follow_sim 的 15+ 条内联断言未单独计数）。

**基线缺口（t5 必须知道）**
1. `B_test_follow_sim.py` 首行报 `bak-b 加载失败（对照采样跳过）`——仓库里没有 `rime_char_overlay.py.bak-b`（旧实现对照件，`*.bak-*` 不入 git）。→ v1.6 的「旧版 CPU/延迟对照采样」在本环境**没有基线数据**，t5 也不要假装有。
2. 各脚本尾部自述的实机项仍**需真人桌面**：真实 WinEventHook 系统投递、真实小狼毫候选框、抓屏三色、DPI 切换。
3. 运行环境落日志：脚本会在 cwd 生成 `error.log`（纯净检出那份在 TMP 里，未污染仓库）。

---

## 2. 用户数据指纹（`%APPDATA%\Rime`）

采集：2026-09-26 11:08:22；复采：11:09（**逐字段比对无漂移**，见 §4）

| 文件 | 字节 | mtime | SHA256 |
|---|---|---|---|
| weasel.custom.yaml | 17426 | 2026-09-05 07:51:18 | `CD340F1438706D8977272A4F4C86977DB3A2E6799FEB911E06AE0A01764AEE8F` |
| weasel.yaml | 26186 | 2025-03-22 08:44:52 | `AEC84018F896CD82A9DD887878BCEE4F979F1917A6D941320FEFD2985F034121` |
| default.custom.yaml | 1336 | 2026-09-07 17:55:29 | `3E2D144B1DEC17F30D9196ECB63187A5880E7A8D30B22DD969847CEF94A69080` |
| rime_ice.custom.yaml | 878 | 2026-09-01 08:52:54 | `3750250F55D453D9EC814D352893648570858D9FD0E9B8F2F7F0706A73090277` |
| user.yaml | 35 | 2026-09-09 15:30:38 | `7C2A052E6C14B7DB61FBF4E0ECDB728EB5546ADC61B1EF95A5E1F5302D6C8DF2` |
| default.yaml | 12877 | 2026-08-30 15:40:11 | `01C890C2B9B6BD8D8F909050437F1732A18DCA51DB03E1856BC3FE762C7C52C9` |
| weasel.custom.yaml.bak | 228 | 2026-08-30 16:40:13 | `A7AA5E2B30882F8B5D5C85D36B9949F525E831870D4D183BF4012F38C70DE8AC` |

现有备份文件（原地、未被本轮工作新增）：`weasel.custom.yaml.bak`、`weasel.custom.yaml.bak-miku-20260901-080455`、`weasel.custom.yaml.bak2`。

### 2.1 配色方案名单（10 个，与预期完全一致）

```
furina_aqua  furina_night  miku_aqua  miku_night  mint_fresh
mint_glass   spring_bloom  spring_bloom_dark  yuzu_orange  yuzu_orange_dark
```

未知方案：**无**；预期缺失：**无**。屏内 scheme 字段行 `preset_color_schemes/<名>/<字段>` 共 **202 行**。

### 2.2 `patch` 段 `style/*` 键值快照（注入逻辑的邻居键，改动不许碰这些）

```yaml
style/color_scheme:          furina_aqua        # 当前生效亮色方案
style/color_scheme_dark:     furina_night       # 当前生效暗色方案
style/horizontal:            true
style/inline_preedit:        false
style/preedit_type:          composition
style/font_point:            15
style/layout/corner_radius:  12
style/layout/hilite_padding: 6
style/layout/shadow_radius:  0
style/layout/shadow_offset_x: 0
style/layout/shadow_offset_y: 0
style/layout/border_width:   0
style/layout/border_height:  0
style/layout/round_corner:   8
style/layout/max_width:      1000
```

（`color_scheme_keys` 探针为空说明：该文件把 `style/color_scheme*` 写在 patch 扁平键里，parser 抽取到的就是上表两条。）

---

## 3. 发布物与工程指纹

| 对象 | 值 |
|---|---|
| `release/config.json` | 274 B，mtime 2026-09-12 17:28:31，sha256 `C18E79A8450A54312D3E02C1C1CDBAD3AA0DCDCB630F67B5C568FAF6C3557F78` |
| config.json 内容 | `image=release\skins\芙芙\image.png`、`layout=horizontal_double`、`side=right`、`layer=above`、`scale=0.6`、`offset=(-132,-132)`、`base_height=300`、`name=芙芙`（**无 `render_mode`、无 `layers`** → 老配置样本，正好可用作「缺键当 compat」的回归输入） |
| `release/RimeSkinOverlay.exe` | 31 216 407 B，mtime 2026-09-10 22:36:52，sha256 `D6D46E5826BC4DA1A5845CA2944C60680F7572756F91CEB3B26A505159B0A2DB`（v1.6 发布件） |
| `release/skins/心灵信标/` | `image.gif` 86978 B `241B5E0F703844592D792603B754DC944FC059BE2F7550B00487DB716BDA3D91`；`skin.json` 435 B `A13CBDB6518E3FFA6D3D2CEB01EFC4E71D91309C8787F456C6C754F45CA2A6EA`（side=center / layer=below / 含 flip_h、corner、feather 字段） |
| `release/skins/芙芙/` | `image.png` 1149424 B `4BF2AC6DC734A100F194B9619DAB8275EBD19627059B0C89ADA3E6B202F22844`；`skin.json` 274 B `C18E79A8450A54312D3E02C1C1CDBAD3AA0DCDCB630F67B5C568FAF6C3557F78`（**与 config.json 同哈希**，即芙芙档案 = 当前生效配置） |
| release/skins 顶层条目 | `心灵信标`、`芙芙`（**无第三项**，无测试残留皮肤） |
| 工程 `skins/` | **不存在**（`SKINS_DIR = HERE/skins`，源码树本来就没有；皮肤档案只存在于 `release/`） |
| 夹具 `char.png` | 1305 B，160×240 RGBA PNG，sha256 `A39F2FC574E4390B94F0C45758E8D8F107A5FB576EBE0A3D8CA1C19C42C99A0C`（存在且合规，**无需现场生成**） |
| git HEAD | `541a2e4bb82aca35a2f1edaffed5dd2c34098a32`（branch `main`） |

---

## 4. 污染判定：**无污染**（判定依据 + 复采证据）

判定时刻的真实状态：
- 配色方案名单 = 预期 10 个，**无未知方案、无缺失**（若有注入误写，必然会多出 `<皮肤名>` 或 `<皮肤名>_dark`）；
- `weasel.custom.yaml` mtime = **2026-09-05**，不是今天（今天 = 2026-09-26）；
- `%APPDATA%\Rime` 里**没有** `weasel.custom.yaml.bak-<时间戳>` / `.bak-restore-<时间戳>`——而 ③ 的 `apply_scheme_injection()` 写前必生成 `weasel.custom.yaml.bak-YYYYmmdd-HHMMSS`、`restore_weasel_backup()` 必生成 `.bak-restore-<ts>`。缺这两类文件 = **从未有注入流程跑过真实配置**；
- `release/skins` 仅 `心灵信标` + `芙芙`，无新条目。

**复采比对**：11:08 与 11:09 两次独立采集，上表 7 个 Rime 文件（含大小/mtime/sha256）、方案名单、`release` exe/config、夹具哈希**逐字段相同**，`pollution_findings = []`。即：本轮 6 个回归脚本 + 并发开发动作，**没有改动任何真实用户数据**。

**t5 污染看门狗（每阶段跑完照此判）**
1. `weasel.custom.yaml` sha256 ≠ `CD340F14…EE8F` → 先解释是不是「用户确认过的注入」，否则按污染处理；
2. 出现 mtime = 当天的 `weasel.custom.yaml.bak-*` → 说明有代码路径写了真机配置；
3. 方案名单多出非预期名字（尤其 `<皮肤名>` / `<皮肤名>_dark`）→ 注入逻辑泄漏到真机；
4. `release/skins/` 多出条目录像 → 测试残留；
5. 处置：用 `.bak` 覆盖回滚（`restore_weasel_backup` 或手工复制），再跑 `WeaselDeployer` 重部署，并把写入路径改成临时目录。

---

## 5. 旁证与观测（非缺陷，供 t5 参考）

- 仓库根 `error.log` 在采集期间仍有 11:08:53–11:09:09 的新条目（`ATL:MockLayerCand4` 等）——那是**并发队友在工作树里跑 B_test_layer_sim.py** 留的；我的基线跑在 TMP，日志落在 TMP 里的 `error.log`（11:08:20 末条），两边未互相干扰。
- 采集期间工作树还新增了未跟踪文件 `B_test_scheme_inject.py`、`make_clean_release.py`（队友 t3/t9 的工作产物）。
- 结论：**当前工作树有并发改动，任何「跑一遍看看」的结论都必须先记下源码 sha256**，否则不可复现。

---

## 6. 存档清单

```
_baseline/v16/
├── baseline_v16.md                 # 本文件（人读）
├── userdata_fingerprint.json       # 机器可读指纹（t5 逐字段 diff 用）
├── _collect_fingerprint.py         # 指纹采集器（只读，可重跑）
├── _run_baseline.py                # 6 脚本回归采集器（在指定检出里跑，不写被测树）
├── B_test_follow_sim.py.txt        # 6 份原始输出（stdout+stderr 合并，UTF-8）
├── B_test_layer_sim.py.txt
├── B_test_misdetect_regress.py.txt
├── B_test_anim_sim.py.txt
├── B_test_fixes.py.txt
└── B_test_extras.py.txt
```

## 7. t5 怎么用这份基线

1. 先 `git log -1` + 记源码 sha256，确认被测源码版本；
2. 跑 6 个 B_test → 与 §1 表逐脚本比 rc 与断言数（不许只比「全绿」，要数量对齐：41 / 13 / 16 / 16 / 54 / ALL PASS）；
3. 跑 `python V_test_v2.py`（骨架在工程根，t5 实装）→ 覆盖 ①②③ 的验收标准与「需真人桌面」标注；
4. 跑 `python _baseline/v16/_collect_fingerprint.py <repo> <out>` → 与 `userdata_fingerprint.json` diff，按 §4 判污染；
5. 需真人桌面的项（真实抓屏三色、真候选框跟随、DPI 切换、30fps 肉眼掉帧）**只能由真人确认**，脚本输出必须标 `NEEDS_HUMAN`。
