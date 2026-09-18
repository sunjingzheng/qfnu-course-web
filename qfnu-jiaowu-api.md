# 强智教务系统 HTTP API 文档（登录、选课与结果查询）

本文档描述曲阜师范大学强智教务系统（`zhjw.qfnu.edu.cn`）的登录、选课与选课结果查询接口。

样本：

- **带实验学时**：专业内跨年级 `xsxkKnjxk`，课名带 `[讲课学时]` / `[实验学时]`。浏览器会走向导，程序**不必拆成两次提交**，直接发最终那条 `knjxkOper`（带 `yxjx0404id` + `cfmyz=1` + 实验班 `jx0404id`）即可同时选上讲课和实验。
- **不带学时（对照）**：公选课 `xsxkGgxxkxk`。`cfbs` / `fzmc` / `parentjx0404id` 均为 `null`，选课函数仍是 `xsxkFun(jx0404id,kcid,cfbs)`，提交只需 `kcid + jx0404id`。

## 基本约定

- **基础地址**：`http://zhjw.qfnu.edu.cn`
- **会话**：所有请求复用同一套 Cookie（会话 Cookie，如 `JSESSIONID`）；验证码、`scode`、`sxh` 与该会话绑定。
- **User-Agent**：全程使用同一条真实桌面版 Chrome 标识，不要发裸 `Mozilla/5.0`：
  `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36`
- **重定向**：登录提交后的 SSO 交接仅允许跟随同源重定向；登录状态验证必须禁止自动跟随重定向，以便识别 `301/302`。

> 响应特征：搜索/选课接口在会话失效时，响应体可能被替换为登录页（同时含 `请输入账号`、`请输入密码`、`请输入验证码`）；账号异地登录时响应体含 `您的账号在其它地方登录`。

## 接口一览

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/` | 初始化会话 |
| `GET` | `/verifycode.servlet` | 获取验证码图片 |
| `POST` | `<OCR 服务>/ocr` | 识别验证码文本 |
| `POST` | `/Logon.do?method=logon&flag=sess` | 获取 `scode` / `sxh` |
| `POST` | `/Logon.do?method=logonLdap` | 提交登录 |
| `GET` | `/jsxsd/framework/xsMain.jsp` | 学生登录状态验证 |
| `GET` | `/jsxsd/framework/jsMain.jsp` | 教师登录状态验证 |
| `GET` | `/jsxsd/xsxk/xklc_list` | 获取选课轮次 |
| `GET` | `/jsxsd/xsxk/xklc_view?jx0502zbid=<轮次ID>` | 轮次详情（浏览器会打开，程序可跳过） |
| `GET` | `/jsxsd/xsxk/xsxk_index?jx0502zbid=<轮次ID>` | 进入选课轮次 |
| `GET` | `/jsxsd/xsxk/xsxk_tzsm` | 选课通知说明（浏览器会打开，程序可跳过） |
| `GET` | `/jsxsd/xsxkkc/comeIn<模块>` | 进入某个选课模块页 |
| `POST` | `/jsxsd/xsxkkc/<模块标识>?<查询参数>` | 搜索课程 |
| `GET` | `/jsxsd/xsxkkc/iscx?jx0404id=&kcid=` | 选课前校验（浏览器会调，语义未完全确认） |
| `GET` | `/jsxsd/xsxkkc/<操作动作>?kcid=&jx0404id=` | 选课 |
| `GET` | `/jsxsd/xkgl/xsxkjgcx` | 选课结果查询页面 |
| `POST` | `/jsxsd/xkgl/loadXsxkjgList` | 加载选课结果列表 |
| `GET` | `/jsxsd/xsxkjg/xsxkkb` | 选课课表页 |

---

## 一、登录

登录流程复用同一套 Cookie，成功后 Cookie 中即带有效会话，供后续搜索/选课请求使用。

### 1.1 初始化会话

```http
GET /
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36
```

- 成功条件：HTTP 状态码 < 400（响应体直接丢弃）。
- 响应中的 Cookie 必须保存并用于后续请求。

### 1.2 获取验证码图片

```http
GET /verifycode.servlet
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36
```

- 成功条件：HTTP 200 且响应体非空（验证码图片二进制数据）。

### 1.3 OCR 识别验证码（外部服务）

OCR 服务地址由调用方提供：

```http
POST <OCR 服务地址>/ocr
Content-Type: application/x-www-form-urlencoded
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36
```

表单字段：

| 字段 | 含义 |
| --- | --- |
| `image` | 验证码图片字节的 base64 编码 |

响应（JSON）：

| 字段 | 含义 |
| --- | --- |
| `code` | 数字或字符串，`200` 表示成功 |
| `data` | 识别出的验证码文本 |
| `message` | 错误信息 |

响应示例：

```json
{
  "code": 200,
  "data": "abcd",
  "message": "ok"
}
```

### 1.4 获取 scode / sxh

```http
POST /Logon.do?method=logon&flag=sess
Content-Type: application/x-www-form-urlencoded
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36

(空请求体)
```

- 响应：纯文本，格式 `scode#sxh`（用 `#` 分割成两段，两段均不能为空）；返回空或 `no` 视为失败。

### 1.5 生成 encoded

输入：用户名、密码、`scode`、`sxh`。

1. 拼接明文：`username + "%%%" + password`。
2. 遍历明文字符，对索引 `0` 至 `19` 的每个字符：先写入该字符；若 `sxh` 在同一索引处是数字 `n`，则从 `scode` 当前游标处顺序取 `n` 个字符追加，并将游标前移（游标耗尽后不再追加）。
3. 索引 `20` 及之后的明文字符原样追加，不再插入 `scode`。

示例：`scode=ABC123`、`sxh=201`、用户名 `u`、密码 `p` 时，明文 `u%%%p` 编码为 `uAB%C%p`。

### 1.6 提交登录

```http
POST /Logon.do?method=logonLdap
Content-Type: application/x-www-form-urlencoded
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36

userAccount=
userPassword=
RANDOMCODE=<OCR 识别出的验证码>
encoded=<按上述规则生成的值>
```

表单字段：

| 字段 | 值 |
| --- | --- |
| `userAccount` | **空字符串**（账号密码不在此提交，凭证在 `encoded` 中，必须留空） |
| `userPassword` | **空字符串**（同上） |
| `RANDOMCODE` | OCR 识别出的验证码 |
| `encoded` | 1.5 步生成的凭证 |

- **成功响应**：通常为 HTTP `302`，先跳转到 `/jsxsd/xk/LoginToXk?method=jwxt&ticqzket=<一次性票据>`，再通过同源重定向进入 `/jsxsd/framework/xsMain.jsp`；客户端只在该登录交接阶段跟随同源重定向，不得跟随外部源，也不要记录票据。
- **失败响应**：正文可能含 `密码错误` / `用户名或密码错误` / `用户名密码错误` / `您提供的用户名或者密码有误`（表示账号密码错误），或 `验证码错误` / `验证码不正确`（表示验证码错误）。

### 1.7 登录状态验证

学生访问：

```http
GET /jsxsd/framework/xsMain.jsp
```

教师访问：

```http
GET /jsxsd/framework/jsMain.jsp
```

- 请求必须禁止自动跟随重定向（与 1.6 的登录交接阶段不同）。
- 成功条件：HTTP 200，且正文包含 `教学一体化服务平台` 或 `glyphicon-class`。

---

## 二、选课轮次

### 2.1 获取轮次列表

```http
GET /jsxsd/xsxk/xklc_list
Referer: http://zhjw.qfnu.edu.cn/jsxsd/framework/xsMain.jsp
```

- 成功：HTTP 200，HTML。
- 页面含选课入口 `#jrxk`（`onclick` 为 `jrxk(jx0502zbid)`）以及：
  - `/jsxsd/xsxk/xsxk_index?jx0502zbid=<轮次ID>`
  - `/jsxsd/xsxk/xklc_view?jx0502zbid=<轮次ID>`
- **`jx0502zbid`**：选课轮次 ID。来源：上述链接的查询参数，或 `#jrxk` / `jrxk('...')`。

### 2.2 轮次详情（可选）

浏览器会打开，程序进入轮次不依赖本页。

```http
GET /jsxsd/xsxk/xklc_view?jx0502zbid=<轮次ID>
Referer: http://zhjw.qfnu.edu.cn/jsxsd/xsxk/xklc_list
```

- 成功：HTTP 200，HTML。含 `onclick="xsxkOpen('<轮次ID>')"`，最终仍跳到 `xsxk_index`。

### 2.3 进入选课轮次

```http
GET /jsxsd/xsxk/xsxk_index?jx0502zbid=<轮次ID>
```

- 成功：HTTP 200，HTML。视为已进入该轮次；后续搜索/选课继续用同一 Cookie。
- 页面上的模块入口（实测）：

| href | 含义 |
| --- | --- |
| `/jsxsd/xsxkkc/comeInBxxk` | 必修选课（26 级 HAR 已点进去，见文末附录；程序主路径不依赖这一行） |
| `/jsxsd/xsxkkc/comeInXxxk` | 选修选课 |
| `/jsxsd/xsxkkc/comeInBxqjhxk` | 本学期计划选课 |
| `/jsxsd/xsxkkc/comeInKnjxk` | 专业内跨年级选课 |
| `/jsxsd/xsxkkc/comeInFawxk` | 计划外选课 |
| `/jsxsd/xsxkkc/comeInGgxxkxk` | 公选课选课 |
| `/jsxsd/xsxkkc/comeInFxzyxk` | 辅修专业选课（本 HAR 未再点进去） |
| `/jsxsd/xsxk/xsxk_tzsm` | 选课通知说明 |
| `/jsxsd/xsxkjg/xsxkkb` | 选课课表 |
| `/jsxsd/xsxkjg/comeXkjglb` | 选课结果列表入口 |
| `/jsxsd/xsxkjg/getTkrzList` | 退课日志 |

### 2.4 选课通知说明（可选）

```http
GET /jsxsd/xsxk/xsxk_tzsm
Referer: http://zhjw.qfnu.edu.cn/jsxsd/xsxk/xsxk_index?jx0502zbid=<轮次ID>
```

- 成功：HTTP 200，HTML 说明页。搜索/选课不依赖本页。

---

## 三、课程搜索

### 3.1 模块与操作映射

| 模块标识 | 中文含义 | 操作动作（oper） | 来源页面（referer） |
| --- | --- | --- | --- |
| `xsxkKnjxk` | 专业内跨年级选课 | `knjxkOper` | `comeInKnjxk` |
| `xsxkBxqjhxk` | 本学期计划选课 | `bxqjhxkOper` | `comeInBxqjhxk` |
| `xsxkXxxk` | 选修选课 | `xxxkOper` | `comeInXxxk` |
| `xsxkFawxk` | 计划外选课 | `fawxkOper` | `comeInFawxk` |
| `xsxkGgxxkxk` | 公选课选课 | `ggxxkxkOper` | `comeInGgxxkxk` |

上表是程序要搜、要提交的五个模块。26 级 HAR 里页面上还有必修入口，搜索标识见文末附录；辅修仍未点进去。

进入模块页：

```http
GET /jsxsd/xsxkkc/comeInGgxxkxk
Referer: http://zhjw.qfnu.edu.cn/jsxsd/xsxk/xsxk_index?jx0502zbid=<轮次ID>
```

- 成功：HTTP 200，HTML。公选页会额外请求 `GET /jsxsd/sys/kaptcha/handleRequestInternal`（JPEG 验证码图）。本 HAR 未提交公选，是否必须带验证码未验证。
- 页面选课按钮脚本：`xsxkFun(jx0404id, kcid, cfbs)`。不带学时的课 `cfbs` 为 `null`/空。浏览器还会按抽签开关拼出另外三种链接形状，见文末附录；程序提交按 4.1 / 4.3，不必解析这些按钮。

### 3.2 搜索请求

```http
POST /jsxsd/xsxkkc/<模块标识>?kcxx=<课程号>&skls=<教师>&sfym=false&sfct=false&sfxx=false&skxq=<星期>&skjc=<节次编码>
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
X-Requested-With: XMLHttpRequest
Referer: http://zhjw.qfnu.edu.cn/jsxsd/xsxkkc/<comeIn*>

iDisplayStart=0&iDisplayLength=10000
```

URL 查询参数：

| 参数 | 含义 |
| --- | --- |
| `kcxx` | 课程号或课名关键字；不传则列出当前模块全部 |
| `skls` | 授课教师（教师姓名） |
| `sfym` | 是否过滤已满。样本均为 `false` |
| `sfct` | 是否过滤冲突。样本均为 `false` |
| `sfxx` | 是否过滤限选。跨年级样本 `false`；**公选课官方页为 `true`** |
| `skxq` | 星期几（仅配置了星期几时携带） |
| `skjc` | 节次编码（仅配置了节次范围时携带，编码规则见 3.3） |

POST 请求体（`application/x-www-form-urlencoded`）：

| 字段 | 值 |
| --- | --- |
| `iDisplayStart` | `0` |
| `iDisplayLength` | `10000`（官方页常用 `15`） |

官方页还会带 DataTables 字段（可省略，只发上面两行也能搜）：

- 跨年级 12 列：`mDataProp_0=kch` … `mDataProp_11=czOper`（含 `fzmc`）
- 公选课 13 列：多 `xxrs`、`szkcflmc`，无 `fzmc` 列

- 成功条件：HTTP 200；`Content-Type` 常标成 `text/html`，正文仍是 JSON。
- 官方 URL 可能多一个空参数 `skxq_xx0103=`，可忽略。各模块官方页还会带另一些模板字段，见文末附录；只发本节通用参数也能搜。

### 3.3 节次编码规则（skjc）

| 用户配置值 | 发送的 skjc 值 |
| --- | --- |
| `1-2` | `1-2-` |
| `3-5` | `3-4-5` |
| `6-7` | `6-7-` |
| `8-9` | `8-9-` |
| `10-12` | `10-11-12` |

- 规则：前四档保留起止两端并在末尾加 `-`；跨三档的档位把中间节次展开。未在表中的值原样透传（如 `5-6` → `5-6`，空值 → 不发送）。

### 3.4 搜索响应 JSON

响应格式：`{"sEcho":"1","iTotalRecords":N,"iTotalDisplayRecords":N,"aaData":[...]}`。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `kch` | string | 课程号 |
| `kcmc` | string | 课程名称 |
| `skls` | string | 授课教师（多人逗号分隔，如 `王彬,朱献贞`） |
| `syrs` | string | 剩余人数（可能为空或 `"0"`） |
| `jx0404id` | string | 教学班 ID |
| `jx02id` | string | 课程 ID |
| `jx0504id` | int | 开课计划 ID |
| `sksj` | string | 上课时间（展示文本，可能含 `<br>`） |
| `xkrs` | int | 选课人数 |
| `pkrs` | int | 排课人数 |
| `xxrs` | int | 限选人数（公选课常见） |
| `dwmc` | string | 开课单位 |
| `ktmc` | string | 课堂名称 |
| `skdd` | string | 上课地点（可能含 `<br>`、顿号、全角空格） |
| `ctsm` | string/null | 冲突说明；空表示无冲突 |
| `zcxqjcList` | array | 周次/星期/节次列表，元素为 `{zc,xq,jc}`（均为 string） |
| `cfbs` | int/null | 拆分标识。带学时：`1`=讲课、`4`=实验；**不带学时为 `null`** |
| `parentjx0404id` | string/null | 父教学班。讲课班等于自身；实验班指向讲课班；不带学时为 `null` |
| `fzmc` | string/null | 实验分组名（`分组01`）；不带学时 / 讲课班为 `null` |
| `xf` | number | 学分 |
| `kcsx` | string/int | 课程属性（公选样本 `"4"`，跨年级样本 `3`） |
| `szkcflmc` | string/null | 公选分类，如 `传统文化` |
| `xqmc` | string | 校区，如 `曲阜校区` |

`aaData` 为空不算错误。

#### 响应示例：不带学时（公选课列表，截断）

```json
{
  "sEcho": "1",
  "iTotalRecords": 55,
  "iTotalDisplayRecords": 55,
  "aaData": [
    {
      "kcmc": "中国古代墓葬",
      "skls": "徐团辉",
      "sksj": "1-18周 星期三 9-10节",
      "skdd": "综合教学楼203",
      "syrs": "0",
      "xkrs": 100,
      "pkrs": 100,
      "xxrs": 100,
      "jx0404id": "202520261006781",
      "jx02id": "006BB0660EE24251A82A1BB92F31D2F3",
      "cfbs": null,
      "fzmc": null,
      "parentjx0404id": null,
      "xf": 2,
      "ktmc": "临班2109",
      "dwmc": "历史文化学院",
      "ctsm": "与已选课程 “习近平新时代中国特色社会主义思想概论” 冲突",
      "szkcflmc": "传统文化",
      "xqmc": "曲阜校区",
      "zcxqjcList": [
        {"zc": "1", "xq": "3", "jc": "09"},
        {"zc": "1", "xq": "3", "jc": "10"}
      ]
    }
  ]
}
```

`sksj` / `skdd` 含 `<br>` 的对照（同一门课两段时间）：

```json
{
  "kcmc": "大学语文",
  "skls": "王彬,朱献贞",
  "sksj": "1-9周 星期四 9-10节<br>10-18周 星期四 9-10节",
  "skdd": "综合教学楼205<br>综合教学楼205",
  "cfbs": null,
  "fzmc": null
}
```

无结果：

```json
{
  "sEcho": "1",
  "iTotalRecords": 0,
  "iTotalDisplayRecords": 0,
  "aaData": []
}
```

（公选模块用专业课号 `kcxx=301043` 会得到上面的空结果；该课在跨年级模块才搜得到。）

#### 响应示例：带实验学时（同一 `jx02id` 三行）

```json
{
  "sEcho": "1",
  "iTotalRecords": 3,
  "iTotalDisplayRecords": 3,
  "aaData": [
    {
      "kcmc": "电子测量[实验学时]",
      "skls": "李媛媛",
      "sksj": "1-18周 星期六 1-2节",
      "skdd": "实验中心C区C609、C611",
      "syrs": "25",
      "jx0404id": "<实验班分组01>",
      "jx02id": "<同一课程ID>",
      "parentjx0404id": "<讲课班ID>",
      "fzmc": "分组01",
      "cfbs": 4,
      "xf": 2.5,
      "ktmc": "23通信班,23电子班",
      "ctsm": ""
    },
    {
      "kcmc": "电子测量[实验学时]",
      "fzmc": "分组02",
      "cfbs": 4,
      "sksj": "1-18周 星期六 3-4节",
      "jx0404id": "<实验班分组02>",
      "parentjx0404id": "<讲课班ID>"
    },
    {
      "kcmc": "电子测量[讲课学时]",
      "sksj": "1-12周 星期二 5-7节",
      "skdd": "格物楼B101",
      "syrs": "50",
      "jx0404id": "<讲课班ID>",
      "parentjx0404id": "<讲课班ID>",
      "fzmc": null,
      "cfbs": 1
    }
  ]
}
```

---

## 四、选课

### 4.1 普通课（不带学时）

与公选 HAR 的页面脚本一致：`xsxkFun(jx0404id, kcid, cfbs)`，`cfbs` 为空时不要造拆分参数。

```http
GET /jsxsd/xsxkkc/<操作动作>?kcid=<课程ID>&jx0404id=<教学班ID>&_=<当前Unix毫秒时间戳>
Accept: */*
X-Requested-With: XMLHttpRequest
Referer: http://zhjw.qfnu.edu.cn/jsxsd/xsxkkc/<来源页面>
```

| 参数 | 含义 |
| --- | --- |
| `kcid` | 候选的 `jx02id` |
| `jx0404id` | 候选的 `jx0404id` |
| `_` | 当前 Unix 毫秒时间戳（防缓存） |

公选 HAR 未抓到 `ggxxkxkOper` 提交，成功形态以跨年级实测为准，见 4.2。

浏览器点选前可能先调：

```http
GET /jsxsd/xsxkkc/iscx?jx0404id=<教学班ID>&kcid=<课程ID>
X-Requested-With: XMLHttpRequest
```

响应示例：

```json
{"status": [false, true]}
```

两布尔含义未确认。选课主路径不依赖它。

### 4.2 选课响应 JSON

响应 `Content-Type` 常为 `text/html`，正文是 JSON：`{"success": ..., "message": "...", "jfViewStr": "..."}`。

| 字段 | 含义 |
| --- | --- |
| `success` | 形态不固定，可能是布尔值、字符串或数组 |
| `message` | 教务系统返回的提示文本 |
| `jfViewStr` | 附加文本，成功样本为空串 |

选课成功：

```json
{
  "success": true,
  "message": "选课成功",
  "jfViewStr": ""
}
```

只提交讲课班、尚未带上实验班时（浏览器向导的中间态，程序不必走）：

```json
{
  "success": true,
  "message": "还有[实验学时]需要选",
  "cfbs": "4",
  "yxcfbs": "1",
  "yxjx0404id": "<讲课班jx0404id>",
  "jfViewStr": ""
}
```

- **`success: true` 不等于整门课选完。** 以 `message` 是否为 `选课成功`、是否还含 `还有[` 为准。

### 4.3 带实验学时：一次提交最终请求

搜索结果里同一 `jx02id` 同时出现 `[讲课学时]`（`cfbs=1`）和 `[实验学时]`（`cfbs=4`，带 `fzmc`）。

**程序只发下面这一条。** `yxjx0404id` 填讲课班，`jx0404id` 填选中的实验班。浏览器向导会先提交讲课再弹窗选实验，那是 UI，不是必须的第二次选课。

```http
GET /jsxsd/xsxkkc/knjxkOper?kcid=<jx02id>&cfbs=4&yxcfbs=1&yxjx0404id=<讲课班jx0404id>&cfmyz=1&jx0404id=<实验班jx0404id>&xkzy=&trjf=
X-Requested-With: XMLHttpRequest
Referer: http://zhjw.qfnu.edu.cn/jsxsd/xsxkkc/comeInKnjxk
```

| 参数 | 取值 | 含义 |
| --- | --- | --- |
| `kcid` | 行的 `jx02id` | 讲课/实验相同 |
| `cfbs` | `4` | 本段为实验学时（与实验行一致） |
| `yxcfbs` | `1` | 一并带上的讲课学时 |
| `yxjx0404id` | 讲课行的 `jx0404id` | 讲课班 |
| `cfmyz` | `1` | 页面写死的拆分确认标记 |
| `jx0404id` | 实验行的 `jx0404id` | 实验班（分组 01/02 选一个） |
| `xkzy` / `trjf` | 空 | 样本未填 |

成功响应：

```json
{
  "success": true,
  "message": "选课成功",
  "jfViewStr": ""
}
```

课表 `/jsxsd/xsxkjg/xsxkkb` 随后会同时出现 `电子测量[讲课学时]` 与 `电子测量[实验学时](分组02)`。

若误只提交讲课班：

```http
GET /jsxsd/xsxkkc/knjxkOper?kcid=<jx02id>&cfbs=1&jx0404id=<讲课班jx0404id>&xkzy=&trjf=&_=<毫秒>
```

会得到 4.2 的「还有[实验学时]需要选」。这时补发最终请求即可，不必再打开 `xsxkKnjxkCfbs` HTML。

浏览器向导（仅作对照，程序可忽略）：

```text
iscx → knjxkOper(cfbs=1, 讲课班)
  → GET xsxkKnjxkCfbs?kcid=&cfbs=4&yxjx0404id=&yxcfbs=1
  → POST xsxkKnjxk?kcid=&cfbs=4&yxjx0404id=   （只列出实验班）
  → knjxkOper(最终请求)
```

实验分组靠 `fzmc` 和时间区分，不要只按地点（分组 01/02 可能同实验室、不同节次）。

---

## 五、选课结果查询

### 5.1 选课结果查询页面

```http
GET /jsxsd/xkgl/xsxkjgcx
```

- 选课结果查询页面，作为 5.2 请求的 `Referer` 上下文。

### 5.2 加载选课结果列表

```http
POST /jsxsd/xkgl/loadXsxkjgList
Content-Type: application/x-www-form-urlencoded
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36
Referer: http://zhjw.qfnu.edu.cn/jsxsd/xkgl/xsxkjgcx

xnxqid=<学期ID>
```

表单字段：

| 字段 | 含义 |
| --- | --- |
| `xnxqid` | 学期 ID（学期标识） |

- 响应：HTML 表格。数据行（`<tr>`，无 `<th>` 表头，且 `<td>` 数量 ≥ 10）按列下标（0 起）取值：

| 列下标 | 字段 |
| --- | --- |
| 1 | 课程名称 |
| 2 | 课程编号 |
| 3 | 上课教师 |
| 5 | 学分 |
| 9 | 选课时间 |

- 选课时间格式示例：`2025-08-25 09:00:19.0`，`Asia/Shanghai` 时区，末尾 `.0`（小数秒）可去除。

### 5.3 选课课表页

```http
GET /jsxsd/xsxkjg/xsxkkb
```

- 进入轮次后、选课成功后浏览器都会打开。HTTP 200，HTML。
- 带学时课程分行显示讲课与实验（实验行课名后带分组）。
- 程序验收可用 5.2 列表，不必解析本页。

---

## 附录：关键请求速查表

| 步骤 | 方法 | URL | 关键参数/特征 | 响应 |
| --- | --- | --- | --- | --- |
| 登录：会话初始化 | GET | `http://zhjw.qfnu.edu.cn` | 读后丢弃响应体 | HTTP < 400 |
| 登录：验证码 | GET | `/verifycode.servlet` | 字节流 | 图片 |
| 登录：OCR | POST | `<OCR>/ocr` | 表单 `image`=base64 | `{"code":200,"data":"..."}` |
| 登录：scode/sxh | POST | `/Logon.do?method=logon&flag=sess` | 空 body | 文本 `scode#sxh` |
| 登录：提交 | POST | `/Logon.do?method=logonLdap` | 账号字段留空 | 同源 SSO 302 |
| 登录：确认 | GET | `/jsxsd/framework/xsMain.jsp` | 禁止跟随重定向 | 200 + 「教学一体化服务平台」 |
| 轮次列表 | GET | `/jsxsd/xsxk/xklc_list` | HTML 含 `jx0502zbid` | 200 HTML |
| 轮次详情 | GET | `/jsxsd/xsxk/xklc_view?jx0502zbid=` | 可跳过 | 200 HTML |
| 进入轮次 | GET | `/jsxsd/xsxk/xsxk_index?jx0502zbid=` | 模块 `comeIn*` 链接 | 200 HTML |
| 进入模块 | GET | `/jsxsd/xsxkkc/comeInGgxxkxk` 等 | 公选页可能加载 kaptcha | 200 HTML |
| 搜索（不带学时） | POST | `/jsxsd/xsxkkc/xsxkGgxxkxk` | 公选 `sfxx=true`；`cfbs=null` | `{"aaData":[...]}` |
| 搜索（带学时） | POST | `/jsxsd/xsxkkc/xsxkKnjxk` | `kcxx`；同时返回讲课+实验行 | 见 3.4 |
| 空搜索 | POST | 同上，`kcxx` 不在该模块 | — | `{"aaData":[],"iTotalRecords":0}` |
| 选课前校验 | GET | `/jsxsd/xsxkkc/iscx?jx0404id=&kcid=` | 可跳过 | `{"status":[false,true]}` |
| 选课（普通） | GET | `/jsxsd/xsxkkc/<oper>?kcid=&jx0404id=&_=` | 无 `cfbs` | `{"success":true,"message":"选课成功"}` |
| 选课（带学时，一次提交） | GET | `knjxkOper?kcid=&cfbs=4&yxcfbs=1&yxjx0404id=<讲课班>&cfmyz=1&jx0404id=<实验班>` | 不要拆两次 | 同上「选课成功」 |
| 结果列表 | POST | `/jsxsd/xkgl/loadXsxkjgList` | 表单 `xnxqid` | HTML 表格 |
| 选课课表 | GET | `/jsxsd/xsxkjg/xsxkkb` | 可跳过 | 200 HTML |

*接口返回内容可能因教务系统版本或角色而变化，实际行为以线上响应为准。*

---

## 附录：26 级 HAR 原始请求补充（脚本可忽略）

> 来源：2026-09-14 `26级选课搜索.har`。下列是浏览器页面实际发出的请求、页面脚本拼出来的链接，以及各模块模板自带的 query 差异。**不是**选课程序的必走路径。正文 3.x / 4.x 已经给出程序该发的请求；开发选课脚本时下面这些可以不看、不实现。

### A. 页面选课按钮的四种形状

搜索结果表「操作」列的选课链接不是服务端返回的，而是页面 `kxkcHandleData()` 用页面内写死的 `qycqxk`（是否启用抽签）与 `cqxklx`（抽签类型）逐行拼出来的：

| 分支 | 生成的链接 | 参数位置 |
| --- | --- | --- |
| `qycqxk!=1` 普通 | `javascript:xsxkOper('jx0404id','','','jx02id','cfbs')` | 1=`jx0404id`，4=`jx02id`，5=`cfbs` |
| `qycqxk=1`、`cqxklx=1` 随机 | `javascript:xsxkFun('jx0404id','jx02id','cfbs')` | 1=`jx0404id`，2=`jx02id`，3=`cfbs` |
| `qycqxk=1`、`cqxklx=2` 报志愿 | `javascript:openXkzyView('jx0404id','jx02id','cfbs')` | 弹窗填志愿，再走 `xsxkOper(...,xkzy,...)` |
| `qycqxk=1`、`cqxklx=3` 投积分 | `javascript:openXkjfView('jx0404id','jx02id','cfbs')` | 弹窗投积分，再走 `xsxkOper(...,trjf,...)` |

- 26 级 HAR 里六个模块页的 `qycqxk` 都是 `"0"`，当场拼的是普通模式（五参 `xsxkOper`）。带学时/公选 HAR 见到的三参 `xsxkFun` 是抽签随机模式。两者都是教学班按钮，提交最终仍落到模块 `*Oper`。
- **同一个函数名跨多个模块**：`xsxkOper` 同时出现在必修与选修，`xsxkFun` 同时出现在本学期计划、计划外、公选课。链接本身不含模块信息。
- 参数 `cfbs` 取自响应的 `cfbs`；该字段为 `null` 时字符串拼接后落成字面量 `'null'`，所以链接里常看到第五/第三个参数是 `'null'`。
- 同页还有 `openkcjj(jx0404id)`（课程简介）、`openjsjj(jsid,jgh)`（教师简介），不是选课链接。

### B. 必修模块搜索（本 HAR 点进去了）

| 模块标识 | 中文含义 | 操作动作（oper） | 来源页面 |
| --- | --- | --- | --- |
| `xsxkBxxk` | 必修选课 | `bxxkOper` | `comeInBxxk` |

搜索体与选修同形，11 列。辅修专业选课（`comeInFxzyxk`）本 HAR 仍没点进去，搜索标识与操作动作未实测。

### C. 各模块官方页搜索 query 的模板差异

官方页实际发的 query（除 `kcxx`/`skls`/`skxq`/`skjc` 外都是页面模板写死的）：

| 模块 | query |
| --- | --- |
| `xsxkBxxk` / `xsxkXxxk` | `kcxx=&skls=&skxq=&skjc=&sfym=false&sfct=false&sfxx=true` |
| `xsxkBxqjhxk` / `xsxkKnjxk` | 同上，末尾多 `&skxq_xx0103=` |
| `xsxkFawxk` | 同上，末尾多 `&skxq_xx0103=&kzyxkbx=0&kzyxkxx=0&kzyxkrx=0&kzyxkqt=0` |
| `xsxkGgxxkxk` | `kcxx=&skls=&skxq=&skjc=&sfym=&sfct=&szjylb=&sfxx=true`（有 `szjylb`，无 `skxq_xx0103`；`sfym`/`sfct` 为空而非 `false`） |

- 三个过滤开关是页面复选框：`sfym`=过滤已满、`sfct`=过滤冲突、`sfxx`=过滤限选。只有 `sfxx` 默认勾选，所以官方页发 `sfxx=true`；`sfym`/`sfct` 默认不勾。程序要全量候选时三项发 `false` 即可（见 3.2）。
- `kcxx` 为空时行为按模块不同：必修、选修、公选课空 `kcxx` 仍有结果（6/4/42 条）；本学期计划、专业内跨年级、计划外空 `kcxx` 返回 0 条，必须带 `kcxx`。
- `skxq_xx0103=`、`kzyxk*`、`szjylb` 都可省略（跨年级/公选 HAR 已验证只发通用参数也能搜）。

### D. 官方页服务端分页与列数

官方页是服务端分页：`iDisplayLength=15`，`iTotalRecords` 是命中总数、`aaData` 只回当前页。26 级 HAR 实测：本学期计划 329/15、计划外 353/15、公选课 42/15。程序按 3.2 显式放大 `iDisplayLength` 即可，不必模仿官方 15 条。

官方 body 的 DataTables 字段：`sEcho=1`、`iColumns`、`sColumns=`、`iDisplayStart`、`iDisplayLength`、`mDataProp_0..n`。列数按模块不同：必修/选修 11 列，本学期计划/专业内跨年级/计划外 12 列，公选课 13 列。这些字段可省略。

### E. 搜索响应里多出来的字段现象

- `cfbs` 不只在带学时的课里出现：计划外模块中 `kch=072126` 同一 `jx02id` 有 `cfbs=1`（电工学[讲课学时]）与 `cfbs=4`（电工学[实验学时]）两行；同一门课的多个教学班共用 `jx02id`、靠 `jx0404id` 区分（`kch=081004` 无机化学1 一次出现 6 行，`cfbs` 均为 `null`）。
- `kch` 与 `jx02id` 可能同值（计划外 `kch=03414008` 的行 `jx02id` 也是 `03414008`），但两者语义不同，不能互相顶替。
- `xkrs`（选课人数）/`syrs`（剩余量）/`xxrs`（限选人数）不是每个模块都返回：必修、选修 11 列里没有，`syrs` 还可能是 `null`。

### F. 浏览器点「选课」时实际发出的请求

页面脚本是 `xsxkOper(jx0404id, xkzy, trjf, kcid, cfbs)`。随机模式的 `xsxkFun(jx0404id, kcid, cfbs)` 只负责弹确认框、隐藏按钮，然后原样转调 `xsxkOper(jx0404id, "", "", kcid, cfbs)`；报志愿/投积分模式由弹窗补上 `xkzy`/`trjf` 后再转调。点一次「选课」浏览器会发三件事：

1. 同步查是否已修读：`GET /jsxsd/xsxkkc/iscx?jx0404id=<教学班ID>&kcid=<课程ID>`，响应示例 `{"status": [false, true]}`。两布尔含义未确认；`status` 为真时页面弹「该课程已修读，是否确认选课？」。选课主路径不依赖它（正文 4.1 已写可跳过）。
2. 页面变量 `sfyzmxk`（是否验证码选课）为 `1` 时改走验证码分支：先把 `jx0404id`/`xkzy`/`trjf`/`kcid`/`cfbs` 填进隐藏表单并取验证码，再带 `verifyCode` 提交。跨年级/公选/26 级 HAR 里该变量都是 `0`，此分支未实测。
3. 主提交（`sfyzmxk!=1`）：

```http
GET /jsxsd/xsxkkc/<操作动作>?kcid=<课程ID>&cfbs=<cfbs>&jx0404id=<教学班ID>&xkzy=<志愿>&trjf=<投入积分>&_=<当前Unix毫秒时间戳>
```

- `kcid` 与 `cfbs` 拼在 URL 上，`jx0404id`/`xkzy`/`trjf` 放在 `$.ajax` 的 `data` 里；jQuery 默认 GET，最终全部落在 query string。`cfbs` 原样透传，**包括字面量 `null`**。
- 普通直选时 `xkzy`/`trjf` 为空。程序按正文 4.1 只带 `kcid` + `jx0404id` 即可；带实验学时按 4.3。

公选 HAR 未抓到 `ggxxkxkOper` 提交，成功形态以跨年级实测为准，见 4.2。
