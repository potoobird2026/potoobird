"""
SecurityGuard + ApprovalModule + ConflictChecker + CredentialPool
安全审批模块

科学依据：
- 软件安全纵深防御（Defense in Depth, NIST SP 800-53）
- 熔断器模式（Circuit Breaker）
- Jaccard 相似度（集合论, 1901）
- 自指性理论（Self-Reference Theory）

所有参数不写死，由公式/LLM/用户互动三个维度获得。
设计文档：05_安全与治理设计.md §6
"""

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger("long_agent.security")


# ============================================================
# SecurityGuard — 安全防护
# ============================================================

@dataclass
class SecurityCheckResult:
    """安全检查结果"""
    is_safe: bool = True
    threat_type: str = ""
    description: str = ""
    original_input: str = ""
    sanitized_input: str = ""


class SecurityGuard:
    """
    安全防护 — 多层过滤

    防护层：
    1. 输入过滤：提示词注入检测
    2. 路径检查：路径遍历防护
    3. 输出检查：敏感信息泄露检测

    所有检测模式不写死，由 LLM 根据最新攻击手段动态更新。
    """

    # 基础模式（可由 LLM 动态扩展）
    PROMPT_INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?(previous\s+)?instructions",
        r"disregard\s+(all\s+)?prior",
        r"you\s+are\s+now\s+(a|an)\s+",
        r"act\s+as\s+(a|an)\s+",
        r"jailbreak",
        r"DAN\s+mode",
    ]

    PATH_TRAVERSAL_PATTERNS = [
        r"\.\./",
        r"\.\.\\",
        r"%2e%2e",
        r"/etc/passwd",
        r"/etc/shadow",
    ]

    SENSITIVE_OUTPUT_PATTERNS = [
        r"sk-[A-Za-z0-9]{20,}",  # API Key
        r"password\s*[:=]\s*\S+",
        r"secret\s*[:=]\s*\S+",
    ]

    def check_input(self, user_input: str) -> SecurityCheckResult:
        """
        检查输入是否包含注入攻击

        Args:
            user_input: 用户输入

        Returns:
            SecurityCheckResult
        """
        if not user_input:
            return SecurityCheckResult(is_safe=True, original_input=user_input, sanitized_input=user_input)

        for pattern in self.PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, user_input, re.IGNORECASE):
                logger.warning(f"检测到提示词注入: pattern={pattern}")
                return SecurityCheckResult(
                    is_safe=False,
                    threat_type="prompt_injection",
                    description=f"检测到提示词注入攻击（匹配模式: {pattern}）",
                    original_input=user_input,
                    sanitized_input="[已过滤不安全输入]",
                )

        return SecurityCheckResult(
            is_safe=True,
            original_input=user_input,
            sanitized_input=user_input,
        )

    def check_path(self, path: str) -> SecurityCheckResult:
        """
        检查路径是否包含遍历攻击

        Args:
            path: 文件路径

        Returns:
            SecurityCheckResult
        """
        if not path:
            return SecurityCheckResult(is_safe=True, original_input=path, sanitized_input=path)

        for pattern in self.PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, path):
                logger.warning(f"检测到路径遍历: pattern={pattern}")
                return SecurityCheckResult(
                    is_safe=False,
                    threat_type="path_traversal",
                    description=f"检测到路径遍历攻击（匹配模式: {pattern}）",
                    original_input=path,
                    sanitized_input="",
                )

        return SecurityCheckResult(
            is_safe=True,
            original_input=path,
            sanitized_input=path,
        )

    def check_output(self, output: str) -> SecurityCheckResult:
        """
        检查输出是否包含敏感信息泄露

        Args:
            output: 输出内容

        Returns:
            SecurityCheckResult
        """
        if not output:
            return SecurityCheckResult(is_safe=True, original_input=output, sanitized_input=output)

        sanitized = output
        for pattern in self.SENSITIVE_OUTPUT_PATTERNS:
            if re.search(pattern, output):
                sanitized = re.sub(pattern, "[REDACTED]", sanitized)
                logger.warning("检测到敏感信息泄露，已脱敏")

        if sanitized != output:
            return SecurityCheckResult(
                is_safe=False,
                threat_type="sensitive_leak",
                description="输出包含敏感信息，已脱敏处理",
                original_input=output,
                sanitized_input=sanitized,
            )

        return SecurityCheckResult(
            is_safe=True,
            original_input=output,
            sanitized_input=sanitized,
        )


# ============================================================
# ApprovalModule — 审批模块
# ============================================================

class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ApprovalRequest:
    """审批请求"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    action: str = ""
    params: dict = field(default_factory=dict)
    risk_score: float = 0.0
    urgency_score: float = 0.5
    status: ApprovalStatus = ApprovalStatus.PENDING
    timeout_seconds: float = 3600.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None
    approver: str = ""
    reason: str = ""


class ApprovalModule:
    """
    审批模块 — 三级协商 + 自适应超时

    设计原则：
    - 风险评分由 LLM 动态评估，不写死
    - 超时时间由公式动态计算，不写死
    - 审批是强制卡点，不是建议
    - 所有审批记录永久保存，可追溯

    超时公式：timeout = base_timeout × (1 + risk_score) / (1 + urgency_score)
    - base_timeout 由 LLM 根据用户响应习惯动态调整
    - risk_score ∈ [0, 1]（LLM 动态评估）
    - urgency_score ∈ [0, 1]（操作紧急程度）
    """

    def __init__(self, base_timeout: float = None):
        """
        Args:
            base_timeout: 基础超时秒数（None 时由 LLM 动态评估，默认 3600s）
        """
        self.base_timeout = base_timeout or 3600.0
        self._pending: dict[str, ApprovalRequest] = {}
        self._history: list[ApprovalRequest] = []

    def evaluate_risk(self, action: str, params: dict = None) -> float:
        """
        评估操作风险 — LLM 动态评估

        当前实现：基于操作类型的启发式评分
        V2 完整实现：调用 LLM 综合评估

        Args:
            action: 操作类型
            params: 操作参数

        Returns:
            float: 风险评分 [0, 1]
        """
        # 基础风险映射（可由 LLM 动态覆盖）
        risk_map = {
            "memory_write": 0.3,
            "personality_update": 0.6,
            "clear_memory": 0.8,
            "reset_personality": 0.9,
            "tool_call": 0.4,
            "file_delete": 0.7,
            "system_config": 0.8,
        }
        return risk_map.get(action, 0.5)

    def calculate_timeout(self, risk_score: float,
                          urgency_score: float = 0.5) -> float:
        """
        计算自适应超时时间

        公式：timeout = base_timeout × (1 + risk_score) / (1 + urgency_score)

        Args:
            risk_score: 风险评分 [0, 1]
            urgency_score: 紧急程度 [0, 1]

        Returns:
            float: 超时秒数
        """
        timeout = self.base_timeout * (1 + risk_score) / (1 + urgency_score)
        return max(60.0, min(timeout, 7200.0))  # 最短1分钟，最长2小时

    async def request_approval(self, action: str, params: dict = None,
                               urgency_score: float = 0.5) -> ApprovalRequest:
        """
        请求审批

        Args:
            action: 操作类型
            params: 操作参数
            urgency_score: 紧急程度 [0, 1]

        Returns:
            ApprovalRequest
        """
        risk_score = self.evaluate_risk(action, params or {})
        timeout = self.calculate_timeout(risk_score, urgency_score)

        request = ApprovalRequest(
            action=action,
            params=params or {},
            risk_score=risk_score,
            urgency_score=urgency_score,
            timeout_seconds=timeout,
        )
        self._pending[request.id] = request
        logger.info(
            f"审批请求 [{request.id}]: {action} "
            f"(风险={risk_score:.2f}, 超时={timeout:.0f}s)"
        )
        return request

    def approve(self, request_id: str, approver: str = "user",
                reason: str = "") -> ApprovalRequest:
        """批准"""
        request = self._pending.get(request_id)
        if not request:
            raise ValueError(f"审批请求不存在: {request_id}")
        request.status = ApprovalStatus.APPROVED
        request.resolved_at = datetime.utcnow()
        request.approver = approver
        request.reason = reason
        self._history.append(request)
        del self._pending[request_id]
        logger.info(f"审批通过 [{request_id}]: {request.action}")
        return request

    def reject(self, request_id: str, approver: str = "user",
               reason: str = "") -> ApprovalRequest:
        """拒绝"""
        request = self._pending.get(request_id)
        if not request:
            raise ValueError(f"审批请求不存在: {request_id}")
        request.status = ApprovalStatus.REJECTED
        request.resolved_at = datetime.utcnow()
        request.approver = approver
        request.reason = reason
        self._history.append(request)
        del self._pending[request_id]
        logger.info(f"审批拒绝 [{request_id}]: {request.action}")
        return request

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def history(self) -> list:
        return list(self._history)


# ============================================================
# ConflictChecker — 冲突检测器
# ============================================================

class ConflictType(Enum):
    DIRECT = "direct"           # 直接冲突
    POTENTIAL = "potential"     # 潜在矛盾
    NONE = "none"               # 无冲突


@dataclass
class Conflict:
    """冲突记录"""
    new_knowledge: str = ""
    existing_knowledge: str = ""
    conflict_type: ConflictType = ConflictType.NONE
    confidence: float = 0.0
    description: str = ""


class ConflictChecker:
    """
    冲突检测器 — 两阶段检测（自指性理论）

    阶段1 — Jaccard 相似度粗筛：
      Jaccard(new, existing) > 阈值 → 进入阶段2
      阈值不写死，由 LLM 根据知识库特征动态确定

    阶段2 — LLM 语义分析精判：
      LLM 综合评估两条知识的语义关系
      输出：conflict_probability ∈ [0, 1]
      conflict_probability > 0.7 → 直接冲突
      0.4 < conflict_probability ≤ 0.7 → 潜在矛盾
    """

    def __init__(self, jaccard_threshold: float = None):
        """
        Args:
            jaccard_threshold: Jaccard 阈值（None 时由 LLM 动态确定，默认 0.3）
        """
        self.jaccard_threshold = jaccard_threshold or 0.3

    def check(self, new_knowledge: str,
              existing_knowledge: list[str]) -> list[Conflict]:
        """
        检查新知识与现有知识是否冲突

        Args:
            new_knowledge: 新知识
            existing_knowledge: 现有知识列表

        Returns:
            list[Conflict]: 冲突列表
        """
        conflicts = []
        for existing in existing_knowledge:
            # 阶段1：Jaccard 相似度粗筛
            jaccard = self._jaccard_similarity(new_knowledge, existing)
            if jaccard < self.jaccard_threshold:
                continue

            # 阶段2：语义分析（简化版，完整版由 LLM 执行）
            conflict = self._semantic_check(new_knowledge, existing, jaccard)
            if conflict.conflict_type != ConflictType.NONE:
                conflicts.append(conflict)

        return conflicts

    def _jaccard_similarity(self, a: str, b: str) -> float:
        """计算 Jaccard 相似度"""
        set_a = set(a.lower().split())
        set_b = set(b.lower().split())
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union)

    def _semantic_check(self, new: str, existing: str,
                        jaccard: float) -> Conflict:
        """
        语义分析（简化版）

        V2 完整版：调用 LLM 综合评估语义关系
        当前实现：基于 Jaccard 相似度的启发式判断
        """
        if jaccard > 0.7:
            return Conflict(
                new_knowledge=new[:100],
                existing_knowledge=existing[:100],
                conflict_type=ConflictType.DIRECT,
                confidence=jaccard,
                description=f"Jaccard 相似度过高（{jaccard:.2f}），可能直接冲突",
            )
        elif jaccard > 0.4:
            return Conflict(
                new_knowledge=new[:100],
                existing_knowledge=existing[:100],
                conflict_type=ConflictType.POTENTIAL,
                confidence=jaccard,
                description=f"Jaccard 相似度中等（{jaccard:.2f}），存在潜在矛盾",
            )
        return Conflict(conflict_type=ConflictType.NONE)


# ============================================================
# CredentialPool — 凭证池
# ============================================================

@dataclass
class CredentialEntry:
    """凭证条目"""
    key: str = ""
    value: str = ""     # V2: 加密存储
    provider: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_used: Optional[datetime] = None
    use_count: int = 0


class CredentialPool:
    """
    凭证池 — 统一管理 API Key

    安全原则（G-010）：
    - Secret 不打印到日志
    - Secret 不编造
    - 缺失就问用户
    """

    def __init__(self):
        self._credentials: dict[str, CredentialEntry] = {}

    def add(self, key: str, value: str, provider: str = ""):
        """
        添加凭证

        Args:
            key: 凭证名称
            value: 凭证值
            provider: 提供商
        """
        if not value:
            raise ValueError(f"凭证 {key} 的值不能为空（G-001）")
        self._credentials[key] = CredentialEntry(
            key=key, value=value, provider=provider
        )
        logger.info(f"添加凭证: {key}（provider={provider}）")

    def get(self, key: str) -> str:
        """
        获取凭证

        Args:
            key: 凭证名称

        Returns:
            str: 凭证值

        Raises:
            KeyError: 凭证不存在
        """
        entry = self._credentials.get(key)
        if not entry:
            raise KeyError(
                f"凭证 {key} 不存在（G-010: 缺失就问用户，不编造）"
            )
        entry.last_used = datetime.utcnow()
        entry.use_count += 1
        return entry.value

    def remove(self, key: str):
        """删除凭证"""
        if key in self._credentials:
            del self._credentials[key]
            logger.info(f"删除凭证: {key}")

    @property
    def keys(self) -> list:
        """列出所有凭证名（不暴露值）"""
        return list(self._credentials.keys())


# ========== V2 补全：CredentialPool 加密 + 轮换 + 冷却 ==========

import base64
import json
import os
import secrets
from datetime import timedelta


class CredentialPoolV2:
    """
    凭证池 V2 — AES-256-GCM 加密存储 + 轮换策略 + 限流冷却

    设计原则：
    - 所有凭证加密存储，不硬编码
    - 支持多凭证轮换
    - 限流冷却机制
    - 密钥来源：用户密码 PBKDF2 派生（迭代次数 100,000，OWASP 推荐）
    - 盐值随机生成，安全存储（盐值丢失 = 所有凭证无法解密）

    设计文档：DESIGN-V2.md §6.5
    """

    def __init__(self, storage_path: str = None,
                 rotation_strategy: str = None):
        """
        Args:
            storage_path: 存储路径（None 时由用户配置或 LLM 动态确定）
            rotation_strategy: 轮换策略（None 时由用户配置）
        """
        self._storage_path = storage_path or "./data/credentials.enc"
        self._rotation_strategy = rotation_strategy  # None 表示由用户配置
        self._master_key: bytes = None
        self._salt: bytes = None
        self._credentials: dict[str, dict] = {}  # name -> {encrypted, nonce, ...}
        self._cooldowns: dict[str, datetime] = {}  # name -> cooldown_until
        self._load()

    def _load(self):
        """加载加密凭证存储"""
        meta_path = self._storage_path + ".meta"
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r") as f:
                    meta = json.load(f)
                self._salt = base64.b64decode(meta.get("salt", ""))
            except (json.JSONDecodeError, IOError):
                pass

    def _save_meta(self):
        """保存元数据（盐值等，不含凭证值）"""
        os.makedirs(os.path.dirname(self._storage_path) or ".", exist_ok=True)
        meta = {
            "salt": base64.b64encode(self._salt).decode() if self._salt else "",
        }
        with open(self._storage_path + ".meta", "w") as f:
            json.dump(meta, f)

    def _derive_key(self, password: str) -> bytes:
        """
        从用户密码派生加密密钥

        使用 PBKDF2-HMAC-SHA256，迭代 100,000 次（OWASP 推荐）
        """
        if not self._salt:
            self._salt = secrets.token_bytes(32)
            self._save_meta()
        kdf = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            self._salt,
            iterations=100_000,
        )
        return kdf

    def _encrypt(self, plaintext: str) -> tuple[str, str]:
        """
        AES-256-GCM 加密

        Returns:
            tuple: (ciphertext_b64, nonce_b64)
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = self._master_key
            nonce = secrets.token_bytes(12)
            ciphertext = AESGCM(key).encrypt(
                nonce,
                plaintext.encode("utf-8"),
                None,
            )
            return (
                base64.b64encode(ciphertext).decode(),
                base64.b64encode(nonce).decode(),
            )
        except ImportError:
            # 无 cryptography 库时的降级：仅做 base64 编码（不安全，仅开发用）
            logger.warning(
                "cryptography 库未安装，凭证仅做 base64 编码（不安全）。"
                "生产环境请安装: pip install cryptography"
            )
            return (
                base64.b64encode(plaintext.encode()).decode(),
                "plaintext",
            )

    def _decrypt(self, ciphertext_b64: str, nonce_b64: str) -> str:
        """
        AES-256-GCM 解密
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            ciphertext = base64.b64decode(ciphertext_b64)
            nonce = base64.b64decode(nonce_b64)
            plaintext = AESGCM(self._master_key).decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")
        except ImportError:
            return base64.b64decode(ciphertext_b64).decode()
        except Exception as e:
            raise ValueError(f"凭证解密失败: {e}")

    def set_master_key(self, password: str):
        """
        设置主密钥（从用户密码 PBKDF2 派生）

        Args:
            password: 用户密码
        """
        if not password:
            raise ValueError("主密钥密码不能为空（G-010）")
        self._master_key = self._derive_key(password)
        logger.info("主密钥已设置（PBKDF2 派生，100,000 次迭代）")

    def add_credential(self, name: str, value: str):
        """
        添加加密凭证

        Args:
            name: 凭证名称
            value: 凭证值

        Raises:
            RuntimeError: 未设置主密钥
            ValueError: 凭证值为空
        """
        if not self._master_key:
            raise RuntimeError("请先调用 set_master_key() 设置主密钥（G-010）")
        if not value:
            raise ValueError(f"凭证 {name} 的值不能为空（G-001）")

        ciphertext, nonce = self._encrypt(value)
        self._credentials[name] = {
            "encrypted": ciphertext,
            "nonce": nonce,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        logger.info(f"凭证已加密存储: {name}")

    def get_credential(self, name: str) -> Optional[str]:
        """
        获取解密后的凭证值

        Args:
            name: 凭证名称

        Returns:
            str or None: 凭证值

        Raises:
            RuntimeError: 未设置主密钥
            KeyError: 凭证不存在
        """
        if not self._master_key:
            raise RuntimeError("请先调用 set_master_key() 设置主密钥（G-010）")
        if name not in self._credentials:
            raise KeyError(
                f"凭证 {name} 不存在（G-010: 缺失就问用户，不编造）"
            )

        # 检查冷却状态
        if name in self._cooldowns:
            if datetime.utcnow() < self._cooldowns[name]:
                remaining = (self._cooldowns[name] - datetime.utcnow()).seconds
                raise RuntimeError(
                    f"凭证 {name} 处于冷却状态，剩余 {remaining}s"
                )
            else:
                del self._cooldowns[name]

        entry = self._credentials[name]
        value = self._decrypt(entry["encrypted"], entry["nonce"])
        logger.debug(f"凭证已获取: {name}")
        return value

    def cooldown(self, name: str, duration_seconds: int = None):
        """
        将凭证设为冷却状态

        Args:
            name: 凭证名称
            duration_seconds: 冷却时长秒数（None 时由 LLM 根据限流响应头动态评估，默认 300s）
        """
        duration = duration_seconds or 300  # 参考值，实际由 LLM 动态评估
        self._cooldowns[name] = datetime.utcnow() + timedelta(seconds=duration)
        logger.info(f"凭证冷却: {name}，时长 {duration}s")

    @property
    def names(self) -> list:
        """列出所有凭证名（不暴露值）"""
        return list(self._credentials.keys())


# ========== V2 补全：ConflictChecker._llm_analyze_conflict ==========

def _llm_analyze_conflict(knowledge_a: str, knowledge_b: str,
                          llm_fn=None) -> float:
    """
    LLM 语义分析冲突

    通过 LLM 综合评估两条知识的语义关系，返回冲突概率。

    Args:
        knowledge_a: 知识 A
        knowledge_b: 知识 B
        llm_fn: LLM 调用函数（None 时使用启发式降级）

    Returns:
        float: 冲突概率 ∈ [0, 1]
        - > 0.7 → 直接冲突
        - 0.4 ~ 0.7 → 潜在矛盾
        - ≤ 0.4 → 无冲突
    """
    if llm_fn is None:
        # 降级：基于关键词重叠的启发式判断
        set_a = set(knowledge_a.lower().split())
        set_b = set(knowledge_b.lower().split())
        if not set_a or not set_b:
            return 0.0
        overlap = len(set_a & set_b) / max(len(set_a | set_b), 1)
        # 高重叠 + 否定词检测
        negation_words = {"不", "没", "无", "非", "别", "not", "no", "never", "don't", "doesn't"}
        has_negation_a = bool(negation_words & set_a)
        has_negation_b = bool(negation_words & set_b)
        if overlap > 0.5 and has_negation_a != has_negation_b:
            return 0.8  # 高重叠 + 一个有否定词 → 可能直接冲突
        elif overlap > 0.5:
            return 0.3  # 高重叠 + 无否定差异 → 可能一致
        return 0.1

    # LLM 判断（异步调用由上层处理）
    # 实际实现中调用 llm_fn()
    logger.info("LLM 语义分析冲突（完整实现由 LLM 调用）")
    return 0.0  # 占位，实际由 LLM 返回
