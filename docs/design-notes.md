# 設計ノート

## 抽出対象セクション (初期スコープ)
以下の2セクションのみを最初の実装対象とする。

- `security > policies`: from-zone/to-zone ごとのポリシールール
- `security > zones`: ゾーン名 ↔ インタフェース対応

除外 (将来対応): address-book、applications、NAT 等

## TTP 出力の JSON 構造 (確定)
```json
{
  "node": "site-a-fw-1",
  "pair": {
    "primary": { "name": "site-a-fw-1", "atypical_interfaces": [...] },
    "secondary": { "name": "site-a-fw-2", "atypical_interfaces": [...] }
  },
  "policies": [
    {
      "from_zone": "trust",
      "to_zone": "untrust",
      "rules": [
        {
          "name": "default-permit",
          "source_address": ["any"],
          "destination_address": ["any"],
          "application": ["any"],
          "action": "permit"
        }
      ]
    }
  ],
  "zones": [
    { "name": "trust", "interfaces": [] },
    { "name": "WAN", "interfaces": ["ge-0/0/1.0", "ge-7/0/1.0"] }
  ]
}
```

**複数値の扱い (parser v0.2.0〜 / netomox 0.15 対応)**: `source_address` / `destination_address` / `application` は常に文字列の配列。
次の 3 形式をすべて同じ配列に正規化する (レビュー F-1 の対応)。

- 同一 match 内の複数行: `application a;` `application b;`
- 1 行のリスト: `application [ a b c ];`
- 複数行のリスト: `application [` (1 行 1 要素) `];`

実装は `ttp_parse()` 内の 2 段階。リスト記法は事前に `key a;` の複数行へ展開し (`_expand_bracket_lists`)、
テンプレート側は各キーを `*` 付きサブグループで収集し、最後に `[{"value": "a"}]` を `["a"]` へ平坦化する (`_flatten_rule_lists`)。
キーが無い場合は `[]`。`action` は `permit|deny|reject` を含む行のみにマッチさせる
(リスト終端の `];` などが `action` に誤マッチして値が壊れるのを防ぐ)。
address-book / address-set / application-set は未対応で、名前は文字列のまま配列に入る (解決しない)。

`inactive: policy NAME { ... }` は無効化されたポリシーなので、前処理 (`_remove_inactive_policies`) でブロックごと除外する
(除外しないと直前のポリシーに合流し、値が蓄積して `action` まで反転する)。

**既知の制約** (未対応):
- ゾーンペア外の `global { policy ... }` は直前の from-zone の rules に合流する。
- `then { permit { application-services ... } }` のようにブロック形式の action は `action` キーが欠落する
  (netomox 側で `''` になり、`vsrx_cluster.j2` は `then { ; }` を出力する)。
- リストの行末コメント (`application [ a b ]; ## comment`) は要素が欠ける。引用符付きで空白を含む名前 (`[ "a b" ]`) は分割される。
- マッチ条件の各値が 1 つも取れなかった場合は `[]` になる (インデントがテンプレートとずれた場合など)。
  `[]` は `controller.yaml` の検証タスクでエラーにする。

## FW コンフィグ検出の設計判断
bgp-policy-parser は node_props.csv (外部クエリ結果) でノード種別を判定しているが、
本ツールでは configs dir に他ルータ・スイッチのコンフィグが混在するため、
ファイル内容のコメントパターンによる自動検出方式を採用した。

## node_pairs を REST で受け取る理由
SRX cluster の node0/node1 ペア情報はコンフィグファイル単体では判断できないため、
呼び出し元が明示的に渡す設計とした。

## configs dir のパス構造 (確定)
`MDDO_CONFIGS_DIR/<network>/<snapshot>/configs/` 以下を `os.walk` で再帰的に走査する。
bgp-policy-parser と同じ `configs/` サブディレクトリ構造を採用した。
実装・手動テストで動作確認済み。

## 将来検討: policy model 変換ステージ
現在のスコープは TTP パースまで (ttp_output への JSON 保存)。
bgp-policy-parser のように TTP raw JSON → 正規化 policy model への変換処理を
第2ステージとして追加することを想定しているが、初期実装には含めない。

## TTP テンプレートのインデント依存
TTP はテンプレート行のインデント（スペース数）を入力行と厳密に照合する。
現テンプレート (`src/template/juniper_srx.ttp`) は JunOS `display inheritance` 出力の
以下のインデントを前提としている:

| インデント | 対応する設定ブロック |
|---|---|
| 4 spaces | `host-name` (system ブロック内) |
| 8 spaces | `from-zone ... to-zone ...`, `security-zone` |
| 12 spaces | `policy NAME`, `interfaces {` |
| 20 spaces | `source-address`, `destination-address`, `application`, `permit`/`deny` |

インデントが異なる（タブ使用、スペース数違い等）場合は一切マッチせず、
エラーも警告も出ずに空の JSON が生成される点に注意。

## 将来検討: address-book / applications の対応
サンプルコンフィグには address-book や applications セクションが含まれないため
初期スコープ外とする。実コンフィグで必要になった時点で TTPテンプレートを拡張する。

## topology エンドポイントの設計

### 2エンドポイント分離の理由
パース（`parsed_result`）と集約・転送（`topology`）を独立したエンドポイントに分けている。
これにより、パース結果を手動確認してから転送する、転送のみ再実行するといった運用が可能になる。

### model-conductor との連携方式
転送は同期 POST で行い、model-conductor のレスポンス（ステータスコード・body）をそのままクライアントに返す。
エラーハンドリングを呼び出し元に委ねることで、このサービス側の実装をシンプルに保つ。

### データ構造: `mddo-topology:l3-node-attributes` ラッパー
model-conductor が期待するトポロジーデータモデルに合わせて、各ノードのデータを
`mddo-topology:l3-node-attributes` キー配下に格納し、全ノードを `{"node": [...]}` でラップする。
ttp_output に保存された JSON オブジェクト全体を `firewall` キーの値としてそのまま埋め込む。

さらに、`"flag": ["firewall"]` フィールドを各ノードのトップレベルに追加する。
このフィールドは netomox-exp が名前空間変換テーブル (`ns_convert_table.json`) を生成する際の
FW ノード判定 (`firewall_node?`) に使用される。

```json
{
  "node": [
    {
      "node-id": "site-a-fw-1",
      "mddo-topology:l3-node-attributes": { "firewall": { ... } },
      "flag": ["firewall"]
    }
  ]
}
```

> **スキーマの canonical definition**: `playground/docs/firewall_node_attributes.md` を参照。
> 出力 JSON キー名は同ドキュメントの「キー命名規則」に従うこと。

### `MODEL_CONDUCTOR_HOST` 環境変数
model-conductor の接続先を `host:port` 形式で受け取る。
デフォルト値 `model-conductor:9292` はコンテナ環境（Docker Compose 等）での
サービス名解決を想定している。ローカル実行時は明示的に上書きする。
