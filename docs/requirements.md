# 要求仕様

## 目的
ネットワーク機器のコンフィグファイルから Firewall policy に関する情報を抽出し、
機械で扱える形式 (JSON) のデータとして保存する。

---

## 対象コンフィグ

- 機器: Juniper SRX
- コンフィグ形式: JunOS 階層型 (hierarchical) コンフィグ
- SRX cluster の node0/node1 はそれぞれ個別ノードとして扱う
- コンフィグファイルは inherited config 形式を前提とする

---

## 機能要件

### FR-1: FW コンフィグの自動検出
- `MDDO_CONFIGS_DIR/<network>/<snapshot>/configs/` 以下を再帰的に走査する
- ファイル内に以下パターンのコメントを含むファイルを FW コンフィグと判定する
  ```
  ## '<nodename>' was inherited from group 'node0'
  ## '<nodename>' was inherited from group 'node1'
  ```
- 判定したファイルからノード名を抽出する

### FR-2: cluster_firewall_pairs との照合
- REST リクエスト body で受け取った `firewall.cluster_firewall_pairs` と、検出されたコンフィグを照合する
- cluster_firewall_pairs に指定されているがコンフィグが見つからない場合: `logger.error` を出力する
- コンフィグは存在するが cluster_firewall_pairs に未指定の場合: `logger.warning` を出力する
- 両方に存在するノードのみを処理対象とする

### FR-3: FW コンフィグのコピー
- 処理対象と判定されたコンフィグファイルを `ttp_input/<network>/<snapshot>/` にコピーする

### FR-4: コンフィグのパース
- コピーした FW コンフィグを TTP (Template Text Parser) でパースする
- 抽出対象 (初期スコープ):
  - `security > policies`: from-zone/to-zone ごとのポリシールール (name, match, action)
  - `security > zones`: ゾーン名とそこに属するインタフェース一覧

### FR-5: パース結果の保存
- パース結果をノードごとに JSON ファイルとして `ttp_output/<network>/<snapshot>/` に保存する
- JSON にはノード名とペア情報 (cluster_firewall_pairs から取得) を含める

### FR-6: 作業ディレクトリの初期化
- REST リクエストを受け取るたびに、以下を全削除してから処理を開始する
  - `ttp_input/<network>/<snapshot>/`
  - `ttp_output/<network>/<snapshot>/`
- これにより前回の処理結果が混入しないことを保証する

### FR-7: REST API (パース)
- 以下のエンドポイントで処理を受け付ける
  ```
  POST /fw_policy/<network>/<snapshot>/parsed_result
  ```
- Request body:
  ```json
  {
    "cluster_firewall_pairs": [
      {
        "primary": { "name": "<node>", "atypical_interfaces": [...] },
        "secondary": { "name": "<node>", "atypical_interfaces": [...] }
      }
    ]
  }
  ```
- `network` と `snapshot` は URL path で指定する

### FR-8: REST API (topology 集約・転送)
- 以下のエンドポイントで処理を受け付ける
  ```
  POST /fw_policy/<network>/<snapshot>/topology
  ```
- 前提: FR-7 (`parsed_result`) が実行済みで `ttp_output/<network>/<snapshot>/` にデータが存在する
- `ttp_output/<network>/<snapshot>/` の全 `*.json` を読み込み、以下の形式に集約する:
  ```json
  {
    "node": [
      {
        "node-id": "<ノード名>",
        "mddo-topology:l3-node-attributes": { "firewall": <ttp_output の JSON オブジェクト> }
      }
    ]
  }
  ```
- 集約データを `http://$MODEL_CONDUCTOR_HOST/conduct/<network>/<snapshot>/topology/layer3/policies` に POST する
- `ttp_output` にファイルが存在しない場合は 404 を返す
- model-conductor のレスポンス（ステータスコード・body）をそのままクライアントに返す

---

## 非機能要件

### NFR-1: 環境変数による設定
以下のディレクトリパスをすべて環境変数で変更できること:

| 変数名 | 用途 | デフォルト |
|---|---|---|
| `MDDO_CONFIGS_DIR` | 全ノードコンフィグのディレクトリ | `./configs` |
| `MDDO_FIREWALL_POLICY_PARSER_DIR` | 作業ディレクトリ基底 | `.` |
| `MDDO_FIREWALL_POLICY_PARSER_CONFIGS_DIR` | FWコンフィグコピー先 | `${MDDO_FIREWALL_POLICY_PARSER_DIR}/ttp_input` |
| `MDDO_FIREWALL_POLICY_PARSER_OUTPUTS_DIR` | TTPパース結果保存先 | `${MDDO_FIREWALL_POLICY_PARSER_DIR}/ttp_output` |
| `MODEL_CONDUCTOR_HOST` | model-conductor 接続先 (`host:port`) | `model-conductor:9292` |

`MDDO_FIREWALL_POLICY_PARSER_CONFIGS_DIR` / `MDDO_FIREWALL_POLICY_PARSER_OUTPUTS_DIR` が
明示的に設定された場合はそちらを優先し、未設定の場合は
`MDDO_FIREWALL_POLICY_PARSER_DIR` からの相対パスをデフォルトとする。

### NFR-2: コンテナ化対応
将来的にコンテナとして動作させることを想定し、
保存先パスはすべて環境変数で外部から注入できる設計とする。

---

## スコープ外 (将来対応)

- `security > address-book` の抽出
- `security > applications` の抽出
- NAT ポリシーの抽出
- Juniper SRX 以外の機器への対応
