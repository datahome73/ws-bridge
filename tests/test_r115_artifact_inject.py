"""R115: _extract_artifact_kv 纯函数测试（10 项验收）。

运行：
    cd /opt/data/ws-bridge && python3 -m pytest tests/test_r115_artifact_inject.py -v
"""
import sys
sys.path.insert(0, "/opt/data/ws-bridge")

from server.ws_server.main import _extract_artifact_kv


class TestExtractArtifactKv:
    """R115: _extract_artifact_kv 纯函数测试（10 项验收）"""

    def test_v1_c_step2_extract(self):
        """验收1: Step2 tech_plan_url+design_decision 正确提取"""
        content = "已完成 ✅ R115 Step 2##tech_plan_url=xxx##design_decision=yyy"
        result = _extract_artifact_kv(content)
        assert result["tech_plan_url"] == "xxx"
        assert result["design_decision"] == "yyy"
        assert len(result) == 2

    def test_v2_d_step3_multiple_keys(self):
        """验收2: Step3 全部4字段"""
        content = (
            "已完成 ✅ R115 Step 3"
            "##commit_sha=abc"
            "##files_changed=a.py,b.py"
            "##commit_description=feat: x"
            "##branch_name=dev"
        )
        result = _extract_artifact_kv(content)
        assert result["commit_sha"] == "abc"
        assert result["files_changed"] == "a.py,b.py"
        assert result["commit_description"] == "feat: x"
        assert result["branch_name"] == "dev"
        assert len(result) == 4

    def test_v3_e_step4_two_keys(self):
        """验收3: Step4 review_report_url+review_decision"""
        content = (
            "已完成 ✅ R115 Step 4"
            "##review_report_url=https://example.com/report.md"
            "##review_decision=通过"
        )
        result = _extract_artifact_kv(content)
        assert result["review_report_url"] == "https://example.com/report.md"
        assert result["review_decision"] == "通过"
        assert len(result) == 2

    def test_v4_f_step5_test_result(self):
        """验收4: Step5 test_result=PASS"""
        content = (
            "已完成 ✅ R115 Step 5"
            "##test_result=PASS"
            "##test_report_url=https://example.com/report.md"
        )
        result = _extract_artifact_kv(content)
        assert result["test_result"] == "PASS"
        assert result["test_report_url"] == "https://example.com/report.md"

    def test_v5_g_step6_merge_sha(self):
        """验收5: Step6 merge_commit_sha"""
        content = (
            "已完成 ✅ R115 Step 6"
            "##merge_commit_sha=ghi9012"
            "##deploy_version=v2.73"
        )
        result = _extract_artifact_kv(content)
        assert result["merge_commit_sha"] == "ghi9012"
        assert result["deploy_version"] == "v2.73"

    def test_v6_no_hash_noop(self):
        """验收6: 无 ## 时返回空 dict"""
        content = "已完成 ✅ R115 Step 3"
        result = _extract_artifact_kv(content)
        assert result == {}

    def test_v7_url_with_equals_untouched(self):
        """验收7: URL 含 = 不被截断（仅第一个 = 做分隔符）"""
        content = "已完成 ✅ R115 Step 2##url=https://example.com?a=1&b=2"
        result = _extract_artifact_kv(content)
        assert result["url"] == "https://example.com?a=1&b=2"

    def test_v8_empty_value_accepted(self):
        """验收8: 空 value 被接受"""
        content = "已完成 ✅ R115 Step 2##key="
        result = _extract_artifact_kv(content)
        assert result["key"] == ""

    def test_v9_invalid_segment_ignored(self):
        """验收9: 无 = 段被忽略"""
        content = "已完成 ✅ R115 Step 2##valid=ok##noequalsign"
        result = _extract_artifact_kv(content)
        assert "valid" in result
        assert "noequalsign" not in result
        assert len(result) == 1

    def test_v10_duplicate_key_overwrites(self):
        """验收10: 同 key 重复，后者覆盖前者"""
        content = "已完成 ✅ R115 Step 2##key=A##key=B"
        result = _extract_artifact_kv(content)
        assert result["key"] == "B"
        assert len(result) == 1

    def test_empty_key_skipped(self):
        """空 key（##=value）被跳过"""
        content = "已完成 ✅ R115 Step 2##=value##valid=ok"
        result = _extract_artifact_kv(content)
        assert "valid" in result
        assert "" not in result
        assert len(result) == 1
