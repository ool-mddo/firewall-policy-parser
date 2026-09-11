# Code Review: Initial Implementation

- **Date**: 2026-09-05
- **Reviewer**: Claude (automated + human-in-the-loop)
- **Effort level**: high
- **Status of findings**: all open

---

## Review Target

| File | Role |
|---|---|
| `src/app.py` | Flask REST API エントリポイント |
| `src/collect_configs.py` | FW コンフィグ検出・照合・コピー・クリーンアップ |
| `src/parse_fw_policy.py` | TTP パース + JSON 保存 |
| `src/template/juniper_srx.ttp` | JunOS SRX 用 TTP テンプレート |
| `test/test_parse.py` | pytest テスト |

レビューの観点:
- Unnecessary abstraction
- Edge cases
- テスト不足
- JunOS config parser としての危険な仮定

---

## Findings

### F-1: 複数の source-address / application が欠落する【危険な仮定・重大】

**Status**: Open

**場所**: `src/template/juniper_srx.ttp:9-11`

**内容**:
TTP テンプレートの `source_address`, `destination_address`, `application` 変数は scalar として定義されている。
JunOS の security policy では match ブロックに同じキーが複数行現れる場合があり、
その場合 TTP は最後にマッチした値だけを残し、それ以前の値を無音で上書きする。

```
# 実際のコンフィグでありうる例
match {
    source-address addr1;
    source-address addr2;   ← addr1 は消える
    application app1;
    application app2;       ← app1 は消える
}
```

現在のサンプルコンフィグがすべて `any` の単一値なのでテストでは検出されないが、
実コンフィグを対象にした場合に誤ったポリシーデータを生成し、セキュリティ分析に影響する。

---

### F-2: インデント数のハードコード【危険な仮定・中】

**Status**: Open

**場所**: `src/template/juniper_srx.ttp` 全体

**内容**:
テンプレートは JunOS 設定ファイルの特定のインデント（4/8/12/20 スペース）を前提としている。
TTP はインデントを含む行全体でマッチングを行うため、
インデントが異なる（例: タブ使用、異なるスペース数）場合は一切マッチしない。
しかもエラーや警告は出ず、空の JSON が生成されるだけである。

---

### F-3: `{{ action }};` の過剰マッチリスク【危険な仮定・中】

**Status**: Open

**場所**: `src/template/juniper_srx.ttp:12`

**内容**:
`{{ action }};` は `then {}` ブロック内の任意の単語に続く `;` にマッチする。
`permit` / `deny` 以外に `reject;` や `discard;` も正しく捕捉できるが、
`then` ブロックに複数のアクション指定（例: `log;` と `permit;`）が含まれる場合、
最後にマッチした値が `action` として記録され、複数の意味を持つアクションが欠落する。

---

### F-4: 同名ファイルが異なるサブディレクトリに存在する場合に上書き【エッジケース・重大】

**Status**: Open

**場所**: `src/collect_configs.py:99`

```python
dst_file = os.path.join(dst_dir, os.path.basename(src_file))
shutil.copy(src_file, dst_file)
```

**内容**:
`dst_file` のファイル名は `os.path.basename(src_file)` で決まる。
configs dir 内の異なるサブディレクトリに同じファイル名が存在すると、
`ttp_input/` での上書きが起きる。
さらに `copy_targets` の2エントリが同じ `dst_file` を参照するため、
2ノードが同じファイルをパースしてしまうが、エラーは一切出ない。

**再現シナリオ**:
`subdir-A/fw.conf` (host-name: fw-1) と `subdir-B/fw.conf` (host-name: fw-2) の場合、
後からコピーされた方のファイルが前者を上書きし、fw-1 の JSON も fw-2 の内容で生成される。

---

### F-5: 同一ノード名を持つファイルが複数存在する場合に無音で上書き【エッジケース・重大】

**Status**: Open

**場所**: `src/collect_configs.py:55`

```python
detected[node_name] = filepath  # 既存エントリを警告なしで上書き
```

**内容**:
configs dir 走査中に、異なるファイルパスから同じ `host-name` が検出された場合、
後から処理されたファイルが `detected` dict のエントリを無音で上書きする。
バックアップコピーや過去のスナップショットファイルが混在していた場合、
誤ったコンフィグがパース対象になる。

---

### F-6: `node_pairs` 内で同一ノードが複数ペアに登場した場合【エッジケース・中】

**Status**: Open

**場所**: `src/collect_configs.py:78`

```python
pair_nodes[node] = pair  # 後勝ちで上書き、エラーなし
```

**内容**:
同一ノードが複数の pair に登場した場合（例: `{"primary":"fw-1","secondary":"fw-2"}` と
`{"primary":"fw-3","secondary":"fw-1"}`）、後勝ちで `pair_nodes["fw-1"]` が
上書きされ、出力 JSON の `pair` フィールドが誤ったペア情報を示す。

---

### F-7: `ttp_result[0][0]` に境界チェックなし【エッジケース・中】

**Status**: Open

**場所**: `src/parse_fw_policy.py:32`

```python
raw = ttp_result[0][0]
```

**内容**:
TTP がマッチなしで `[[]]` を返した場合、`IndexError` が発生し Flask が 500 を返す。
空のコンフィグ、テンプレート不一致、TTP_TEMPLATE ファイルの欠損時に起きる。

---

### F-8: inherit コメントあり・host-name なしの場合に無音スキップ【エッジケース・中】

**Status**: Open

**場所**: `src/collect_configs.py:30`

```python
node_name = _detect_node_name(text)
if node_name:
    detected[node_name] = filepath
# node_name が None の場合、何もログに出ない
```

**内容**:
`_INHERIT_PATTERN` にマッチしたにもかかわらず `host-name` が見つからない場合
（フォーマット異常、`host-name` 行がない等）、`_detect_node_name` は `None` を返し、
そのファイルは検出リストに入らない。
呼び出し側の `collect_configs` は `logger.error("config not found")` だけを出力し、
根本原因（フォーマット異常）がログに残らない。

---

### F-9: ループ途中の例外でファイルが部分的に残る【エッジケース・中】

**Status**: Open

**場所**: `src/parse_fw_policy.py:48`

**内容**:
`parse_fw_configs` のノードループに例外ハンドリングがない。
node1 の保存成功後に node2 の処理で例外（OSError、TTP クラッシュ等）が発生すると、
`ttp_output/` に node1.json だけが残り、node2.json はない中途半端な状態になる。
Flask は 500 を返すが、呼び出し元は「何も保存されなかった」と「部分的に保存された」を
区別できない。cleanup は次のリクエストまで実行されない。

---

### F-10: `collect_configs()` の error/warning ログ検証がない【テスト不足】

**Status**: Open

**場所**: `test/test_parse.py`

**内容**:
`test_node_pairs_validation` は `caplog` を import しているが、
実際に `logger.error` / `logger.warning` が呼ばれたことをアサートしていない。
node_pairs に存在しないノードや、コンフィグが見つからないケースでのログ出力が
保証されていない。

---

### F-11: `_build_output()` の正規化を直接テストするケースがない【テスト不足】

**Status**: Open

**場所**: `test/test_parse.py`

**内容**:
`_build_output()` が interfaces の list を正しく平坦化すること（`[{"interface": "ge-..."}]`
→ `["ge-..."]`）を直接検証するテストがない。
また、zones に interfaces がない場合（trust/untrust）で `interfaces: []` が正しく
補完されることも未検証。

---

### F-12: TTP が空結果を返した場合のテストがない【テスト不足】

**Status**: Open

**場所**: `test/test_parse.py`

**内容**:
テンプレートにマッチしないコンフィグを渡した場合（`ttp_parse()` が `[[{}]]` を返す場合）や、
さらに `[[]]` を返した場合（F-7 の IndexError トリガー）のテストがない。

---

### F-13: 複数の source-address を含むコンフィグのテストがない【テスト不足】

**Status**: Open

**場所**: `test/test_parse.py`

**内容**:
F-1 で指摘した複数値問題を再現するテスト入力（同一 match ブロックに複数の
source-address）がなく、問題を自動検出できない状態になっている。

---

### F-14: `collect_configs()` フル統合テストがない【テスト不足】

**Status**: Open

**場所**: `test/test_parse.py`

**内容**:
`collect_configs()` 関数全体（node_pairs 照合 → ファイルコピー → 返却構造）を
確認するテストがない。現状は `detect_fw_configs` と `_detect_node_name` の単体テストのみ。

---

## Risks / Concerns

| リスク | 影響 | 発生条件 |
|---|---|---|
| 複数アドレス値の欠落 (F-1) | 誤ったポリシー分析 | 実コンフィグがサンプルと異なる |
| 同名ファイル上書き (F-4) | 誤ったノードデータ生成 | サブディレクトリ構成による同名ファイル |
| 同一ノード名の重複検出 (F-5) | 誤ったコンフィグをパース | バックアップファイル混入 |
| IndexError によるクラッシュ (F-7) | REST 500 | コンフィグがテンプレートにマッチしない |
| インデント不一致 (F-2) | 全データが空 JSON | JunOS バージョンや取得方法による出力差異 |

最も優先度が高い修正は **F-1**（複数値問題）と **F-4**（ファイル名衝突）であり、
いずれも実コンフィグ投入時にサイレントに誤データを生成する可能性がある。

---

## Suggested Changes

| # | 対象 | 変更内容 |
|---|---|---|
| 1 | `juniper_srx.ttp` | `source_address` / `destination_address` / `application` をリスト収集（`*` 付きサブグループ）に変更 |
| 2 | `collect_configs.py:99` | `dst_file` のファイル名にノード名をプレフィックスとして付与し衝突を回避 |
| 3 | `collect_configs.py:55` | 同一ノード名の重複検出時に `logger.warning` を出力 |
| 4 | `collect_configs.py:78` | 同一ノードが複数 pair に登場した場合に `logger.warning` を出力 |
| 5 | `parse_fw_policy.py:32` | `ttp_result[0][0]` へのアクセス前に境界チェック（`IndexError` ガード）を追加 |
| 6 | `collect_configs.py:30` | inherit コメントあり・hostname 取得失敗時に `logger.warning` を追加 |
| 7 | `test/test_parse.py` | `caplog` を使ったログ出力の検証を追加 |
| 8 | `test/test_parse.py` | `_build_output()` の正規化テストを追加 |
| 9 | `test/test_parse.py` | 複数 source-address を含むサンプルを用意してテストを追加 |

---

## Open Questions

1. **F-1 の修正方針**: match 内の複数アドレスを TTP テンプレートのサブグループで
   リスト収集するか、パース後の Python コードで整形するか。
   TTP のサブグループ方式はテンプレートが複雑になるため、
   Python 側での整形（単一値なら list 化、list ならそのまま）が現実的か。

2. **F-2 のインデント**: inherited config の出力は常に 4-space インデントと仮定してよいか。
   `show configuration | display inheritance` の出力形式はバージョンや
   取得方法（NETCONF/CLI）によって変わるか確認が必要。

3. **F-3 の action 複数値**: `then { log; permit; }` のような複合アクションを
   将来サポートするか。サポートする場合は action もリスト化が必要。

4. **F-4 のファイル名衝突**: 実際の運用で configs dir のファイル名がどのような
   命名規則になっているかによって、対処の優先度が変わる。
   現状のサンプルは `<nodename>.config.inheritance` 形式のため衝突しないが、
   汎用性のため対処を推奨。

5. **F-9 の partial failure**: 途中失敗時にそれまでの出力を残すか・全削除するかは
   設計方針として決める必要がある。REST の冪等性を重視するなら全削除が望ましい。
