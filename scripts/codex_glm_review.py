#!/usr/bin/env python3
"""
Codex-GLM Harness - Code Review Powered by GLM-5.1
====================================================

Performs deep code analysis similar to OpenAI Codex but using GLM-5.1 API.
"""

import os
import sys
import json
import re
import ast
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

# Try to import openai, fallback to requests
OPENAI_AVAILABLE = False
REQUESTS_AVAILABLE = False

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    pass

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    pass


@dataclass
class Issue:
    line: int
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    category: str  # syntax, hallucination, logic, security, integration
    description: str
    fix: str
    code_snippet: str = ""


@dataclass
class ReviewResult:
    file: str
    issues: List[Issue]
    passed: bool


class GLMCodeReviewer:
 """Code reviewer powered by GLM-5.1 via OpenAI-compatible API."""
 
 def __init__(self):
 # GLM-5.1 via OpenAI-compatible endpoint
 self.api_key = os.getenv("GLM_ZAI_API_KEY", "41d5841a97e24f63a05eb026e7ff6d6b")
 self.base_url = "https://open.bigmodel.cn/api/paas/v4"
 self.model = "glm-5.1"
 
 if OPENAI_AVAILABLE:
 self.client = OpenAI(
 api_key=self.api_key,
 base_url=self.base_url
 )
 else:
 self.client = None
 
 def _call_llm(self, prompt: str) -> str:
 """Call GLM-5.1 API via OpenAI-compatible endpoint."""
 if OPENAI_AVAILABLE and self.client:
 try:
 response = self.client.chat.completions.create(
 model=self.model,
 messages=[{"role": "user", "content": prompt}],
 max_tokens=4096,
 temperature=0.2
 )
 return response.choices[0].message.content
 except Exception as e:
 print(f"OpenAI client error: {e}")
 
 # Fallback to requests
 if REQUESTS_AVAILABLE:
 headers = {
 "Authorization": f"Bearer {self.api_key}",
 "Content-Type": "application/json"
 }
 data = {
 "model": self.model,
 "messages": [{"role": "user", "content": prompt}],
 "max_tokens": 4096,
 "temperature": 0.2
 }
 try:
 response = requests.post(
 f"{self.base_url}/chat/completions",
 headers=headers,
 json=data,
 timeout=120
 )
 result = response.json()
 if "choices" in result and len(result["choices"]) > 0:
 return result["choices"][0]["message"]["content"]
 else:
 print(f"Unexpected response: {result}")
 except Exception as e:
 print(f"LLM API error: {e}")
 
 return "Error: Unable to call LLM API"
    
    def review_file(self, filepath: str) -> ReviewResult:
        """Review a single file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            return ReviewResult(
                file=filepath,
                issues=[Issue(0, "CRITICAL", "syntax", f"Cannot read file: {e}", "Fix file permissions")],
                passed=False
            )
        
        # Determine file type
        ext = Path(filepath).suffix
        
        # Pre-check syntax for Python
        syntax_issues = []
        if ext == '.py':
            try:
                ast.parse(content)
            except SyntaxError as e:
                syntax_issues.append(Issue(
                    line=e.lineno or 1,
                    severity="CRITICAL",
                    category="syntax",
                    description=f"Python syntax error: {e.msg}",
                    fix=f"Fix syntax at line {e.lineno}",
                    code_snippet=e.text or ""
                ))
        elif ext == '.sh':
            result = subprocess.run(['bash', '-n', filepath], capture_output=True, text=True)
            if result.returncode != 0:
                syntax_issues.append(Issue(
                    line=1,
                    severity="CRITICAL",
                    category="syntax",
                    description=f"Shell syntax error: {result.stderr}",
                    fix="Check shell syntax"
                ))
        elif ext == '.json':
            try:
                json.loads(content)
            except json.JSONDecodeError as e:
                syntax_issues.append(Issue(
                    line=1,
                    severity="CRITICAL",
                    category="syntax",
                    description=f"JSON syntax error: {e}",
                    fix="Fix JSON formatting"
                ))
        
        # Use GLM for deeper analysis
        prompt = f"""Review this {ext} code file for issues. Be extremely thorough:

FILE: {filepath}

```
{content}
```

Analyze for:
1. **Hallucinated/non-functional code** - functions that don't exist, undefined variables, broken imports
2. **Logic errors** - incorrect algorithms, edge cases, wrong calculations
3. **Security issues** - hardcoded secrets, injection vulnerabilities
4. **Integration problems** - API mismatches, missing dependencies

Format your response as JSON:
{{
    "issues": [
        {{
            "line": 42,
            "severity": "CRITICAL|HIGH|MEDIUM|LOW",
            "category": "hallucination|logic|security|integration",
            "description": "specific description",
            "fix": "specific fix suggestion"
        }}
    ],
    "summary": "Brief summary of code quality"
}}

If no issues found, return empty issues array."""
        
        response = self._call_llm(prompt)
        
        # Parse GLM response
        issues = []
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                for issue_data in data.get('issues', []):
                    issues.append(Issue(
                        line=issue_data.get('line', 1),
                        severity=issue_data.get('severity', 'MEDIUM'),
                        category=issue_data.get('category', 'logic'),
                        description=issue_data.get('description', 'Unknown issue'),
                        fix=issue_data.get('fix', 'Review manually'),
                        code_snippet=issue_data.get('code_snippet', '')
                    ))
        except Exception as e:
            print(f"Warning: Could not parse GLM response for {filepath}: {e}")
            print(f"Raw response: {response[:500]}...")
        
        # Combine syntax and GLM issues
        all_issues = syntax_issues + issues
        
        return ReviewResult(
            file=filepath,
            issues=all_issues,
            passed=len([i for i in all_issues if i.severity == "CRITICAL"]) == 0
        )
    
    def review_directory(self, dirpath: str, extensions: List[str] = None) -> List[ReviewResult]:
        """Review all files in a directory."""
        if extensions is None:
            extensions = ['.py', '.sh', '.js', '.ts', '.json', '.yaml', '.yml']
        
        results = []
        for ext in extensions:
            for filepath in Path(dirpath).rglob(f"*{ext}"):
                print(f"Reviewing: {filepath}")
                result = self.review_file(str(filepath))
                results.append(result)
        
        return results


def print_report(results: List[ReviewResult]):
    """Print formatted review report."""
    print("=" * 80)
    print("CODEX-GLM CODE REVIEW REPORT")
    print("=" * 80)
    print(f"Powered by GLM-5.1 | Reviewed {len(results)} files")
    print()
    
    total_issues = 0
    critical = 0
    high = 0
    medium = 0
    low = 0
    
    for result in results:
        print(f"\n📄 {result.file}")
        print("-" * 80)
        
        if not result.issues:
            print("  ✅ No issues found")
            continue
        
        for issue in result.issues:
            icon = "🔴" if issue.severity == "CRITICAL" else \
                   "🟠" if issue.severity == "HIGH" else \
                   "🟡" if issue.severity == "MEDIUM" else "🔵"
            
            print(f"  {icon} Line {issue.line}: [{issue.severity}] {issue.category.upper()}")
            print(f"     {issue.description}")
            print(f"     Fix: {issue.fix}")
            
            total_issues += 1
            if issue.severity == "CRITICAL": critical += 1
            elif issue.severity == "HIGH": high += 1
            elif issue.severity == "MEDIUM": medium += 1
            else: low += 1
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total files reviewed: {len(results)}")
    print(f"Total issues: {total_issues}")
    print(f"  🔴 Critical: {critical}")
    print(f"  🟠 High: {high}")
    print(f"  🟡 Medium: {medium}")
    print(f"  🔵 Low: {low}")
    print()
    
    if critical > 0:
        print("❌ REVIEW FAILED - Critical issues must be fixed before deployment")
    elif high > 0:
        print("⚠️  REVIEW WARNING - High severity issues should be addressed")
    else:
        print("✅ REVIEW PASSED - Code is ready for deployment")
    
    print("=" * 80)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Codex-GLM Code Review Harness")
    parser.add_argument("--file", "-f", action="append", help="Specific file(s) to review")
    parser.add_argument("--dir", "-d", help="Directory to review")
    parser.add_argument("--extensions", "-e", default=".py,.sh,.js,.ts,.json", help="File extensions to check (comma-separated)")
    parser.add_argument("--output", "-o", help="Output file for JSON report")
    parser.add_argument("--summary-only", "-s", action="store_true", help="Only print summary")
    
    args = parser.parse_args()
    
    reviewer = GLMCodeReviewer()
    
    results = []
    
    if args.file:
        for f in args.file:
            results.append(reviewer.review_file(f))
    elif args.dir:
        extensions = args.extensions.split(",") if args.extensions else [".py", ".sh"]
        results = reviewer.review_directory(args.dir, extensions)
    else:
        print("Error: Specify --file or --dir")
        return 1
    
    # Print report
    if not args.summary_only:
        print_report(results)
    else:
        # Just print summary
        critical = sum(1 for r in results for i in r.issues if i.severity == "CRITICAL")
        print(f"Review complete: {len(results)} files, {critical} critical issues")
    
    # Save JSON report
    if args.output:
        report = {
            "harness": "codex-glm",
            "model": "glm-5.1",
            "files": len(results),
            "results": [
                {
                    "file": r.file,
                    "passed": r.passed,
                    "issues": [asdict(i) for i in r.issues]
                }
                for r in results
            ]
        }
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"Report saved to: {args.output}")
    
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
