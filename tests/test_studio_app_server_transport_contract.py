import re
import unittest
from pathlib import Path


SKILL_PATH = Path(__file__).resolve().parents[1] / "SKILL.md"


class StudioAppServerTransportContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = SKILL_PATH.read_text(encoding="utf-8")

    def test_exception_is_exactly_transport_scoped(self):
        self.assertIn("transport=studio_app_server_v1", self.skill)
        self.assertIn("application/developer context", self.skill)
        self.assertIn("没有该精确 transport 标记", self.skill)
        self.assertRegex(self.skill, r"普通 Codex 主对话、CLI 或其他 App Server 调用仍必须使用图片执行子 Agent")

    def test_root_wrapper_keeps_canonical_fast8_boundaries(self):
        required = [
            "prepare --render-action",
            "await eval(action)",
            "A–H 逐席会话",
            "第二 runner",
            "第二 semaphore",
            "第二 Judge",
            "generatedImage(...)",
            "image(...)",
            "中央 cap5",
            "ticket → savedPath → receipt",
        ]
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.skill)

    def test_fallback_requires_idle_executor_or_explicit_dispatch_failure(self):
        exception = re.search(
            r"严格限域的 Studio App Server 兼容例外.*?不得援引本例外。",
            self.skill,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(exception)
        text = exception.group(0)
        self.assertIn("连续 180 秒", text)
        self.assertIn("没有任何 `interacted`、command/tool activity 或中央 claim", text)
        self.assertIn("宿主明确报告不能直接派发首 turn", text)
        self.assertIn("先中断该空闲子 Agent", text)
        self.assertIn("两种路由不得并存", text)

    def test_single_image_edit_uses_the_same_scoped_root_exception(self):
        required = [
            "正式 `single_image_edit`",
            "Studio 根 turn 从开始就是唯一机械 executor",
            "prepare → claim → ImageGen exactly once → complete",
            "failed/cancelled",
            "host-finalize marker",
            "不覆盖父图",
            "不修改 selection",
            "不增加 Judge/Reviewer",
            "单图修改仍由图片执行子 Agent承载",
        ]
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.skill)


if __name__ == "__main__":
    unittest.main()
