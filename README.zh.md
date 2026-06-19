# vrc-profile-proof

`vrc-profile-proof` 是一个非官方 Python 库，用于证明某人可以控制一个 VRChat 个人资料。它创建一个短期有效的挑战字符串，要求用户将其放入公开个人简介中，然后重新获取该资料并验证令牌。

## 特性

- 不会向最终用户索取 VRChat 凭据或 session cookie。
- 每个挑战都包含独立的随机数，不可重用。
- 挑战默认 10 分钟后过期，且只能成功验证一次。
- 服务密钥默认在进程启动时随机生成，重启后未完成的挑战自动失效。
- 每次验证都会重新获取最新的个人资料，不进行缓存。
- 使用 Unicode NFKC 归一化，兼容半角/全角字符变化。
- 返回的挑战结果包含完整的 VRChat 个人资料以及标准化的信任等级。
- 支持可配置的全局及单用户内存级速率限制。

## 安装

```powershell
python -m pip install -e .
```

本包无运行时依赖，需要 Python 3.11 或更新版本。

## 库调用示例

```python
from vrc_profile_proof import VRChatClient, VerificationService

client = VRChatClient(user_agent="my-app/1.0 operator@example.com")
client.login_with_cookie("authcookie_xxxxx")

service = VerificationService(client)

challenge = service.start_verification(
    "usr_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    context_label="My App Profile Verify",
)

print(challenge.text)
print(challenge.user_id)
print(challenge.trust_rank.value)

# 用户将 challenge.text 放入 VRChat 个人简介后：
result = service.verify(challenge.challenge_id)
if result.success:
    print(result.user_id)
```

`start_verification()` 接受用户 ID、包含用户 ID 的 VRChat 个人资料 URL，或显示名称。显示名称搜索可能产生歧义，调用方应捕获 `AmbiguousUserError` 并要求用户选择合适的候选。

## 挑战字符串格式

挑战字符串格式如下：

```
【My App Profile Verify - vrcverifyxxxxxxxxxxxxxxxxxxxxxxxxxx】
```

用途标签会参与 HMAC 计算，核心令牌由字母和数字组成。验证时对个人简介和令牌进行 Unicode NFKC 归一化后搜索该令牌，因此 VRChat 对个人简介中的标点或空格调整通常不会影响验证。

## 速率限制

默认策略为用户的误操作保留了一定的容错空间：

- 全局：每 60 秒最多 60 次创建/检查操作。
- 单用户：每次检查至少间隔 2 秒。
- 单用户：允许连续 5 次检查失败。
- 第 5 次连续失败后：冷却 5 分钟。
- 一次成功检查会重置该用户的失败计数。
- 当用户超过 5 分钟没有再次失败时，失败计数也会重置。

可在创建限速器时自定义这些参数：

```python
from vrc_profile_proof import (
    GlobalRateLimit, UserRateLimit, VerificationRateLimiter, VerificationService,
)

limiter = VerificationRateLimiter(
    global_policy=GlobalRateLimit(max_operations=120, window_seconds=60),
    user_policy=UserRateLimit(
        min_interval_seconds=2,
        failures_before_cooldown=5,
        failure_reset_seconds=300,
        cooldown_seconds=600,
    ),
)
service = VerificationService(client, rate_limiter=limiter)
```

`RateLimitExceeded` 包含 `scope` 和 `retry_after`，方便 HTTP 服务返回准确的 `429` 响应。

## 命令行示例

将 `.env.example` 复制为 `.env`，填入服务运行者的 cookie 和 User-Agent，然后运行：

```powershell
vrc-profile-proof
```

cookie 属于服务运行者。不要向最终用户索取 VRChat 密码、auth cookie、token 或 session 数据。

## 安全说明

- 验证成功表示在验证当时该用户控制了对应的 VRChat 个人资料，并非法律身份证明。
- 未完成的挑战仅存在于 `VerificationService` 所在进程中，重启后失效。
- 将信任等级视为反滥用信号，而非账号合法性的保证。
- 请使用描述清晰的 User-Agent，遵守 VRChat API 使用规则，遇到 `429` 时进行退避。
- 在挑战中展示自己的服务名称，不要暗示该流程是 VRChat 官方的登录方式。

## 开发

```powershell
python -m unittest discover -s tests -v
```

## 免责声明

本项目与 VRChat Inc. 无关，不受其背书或赞助。它是一种个人资料控制权验证，而非官方的 `Login with VRChat` 或 OAuth。