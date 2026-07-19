#!/usr/bin/env python3
"""
Standalone script for checking files for prompt injection patterns.
Can be used with pre-commit hooks or CI/CD pipelines.

Specifically designed for USPTO PTAB MCP to detect:
- Unicode steganography attacks (emoji-based hiding from Repello.ai article)
- PTAB-specific injection attempts (trial/appeal data extraction, API bypass)
- Standard prompt injection patterns

Usage:
    python check_prompt_injections.py file1.py file2.txt ...
    python check_prompt_injections.py src/ tests/ *.md
    python check_prompt_injections.py --baseline src/ tests/

Exit codes:
    0 - No prompt injections found (or only baseline findings)
    1 - Prompt injections detected (NEW findings not in baseline)
    2 - Error occurred

Baseline Feature:
    - Creates/updates a baseline file tracking known findings
    - Only flags NEW findings not in the baseline
    - Use --update-baseline to add new legitimate findings to baseline
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Set

from ptab_prompt_injection_detector import PTABPromptInjectionDetector


BASELINE_FILE = Path('.prompt_injections.baseline')


def get_fingerprint(filepath: Path, line_number: int, match: str) -> str:
    """Create a unique fingerprint for a finding."""
    content = f"{filepath}:{line_number}:{match}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def load_baseline() -> Dict[str, Dict[str, str]]:
    """Load baseline from file."""
    if not BASELINE_FILE.exists():
        return {}

    try:
        with open(BASELINE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_baseline(baseline: Dict[str, Dict[str, str]]) -> None:
    """Save baseline to file."""
    with open(BASELINE_FILE, 'w', encoding='utf-8') as f:
        json.dump(baseline, f, indent=2, sort_keys=True)


def check_file(filepath: Path, detector: PTABPromptInjectionDetector) -> List[Tuple[int, str]]:
    """
    Check a single file for prompt injection patterns.

    Returns:
        List of (line_number, match) tuples
    """
    try:
        # Skip binary files
        if not filepath.is_file():
            return []

        # Only check text-based files (including PTAB-specific file types)
        text_extensions = {
            '.py', '.txt', '.md', '.yml', '.yaml', '.json', '.js', '.ts',
            '.html', '.xml', '.csv', '.rst', '.cfg', '.ini', '.toml',
            '.log', '.env', '.sh', '.bat', '.ps1'
        }
        if filepath.suffix.lower() not in text_extensions and filepath.suffix:
            return []

        # Skip files that are likely to contain legitimate security examples or documentation
        excluded_files = {
            # Security documentation and tools
            'SECURITY_SCANNING.md', 'SECURITY_GUIDELINES.md', 'security_examples.py', 'test_security.py',
            'ptab_prompt_injection_detector.py', 'check_prompt_injections.py',
            # Documentation files likely to contain examples
            'README.md', 'PROMPTS.md', 'CLAUDE.md', 'INSTALL.md',
            # Deployment and configuration scripts
            'linux_setup.sh', 'windows_setup.ps1', 'manage_api_keys.ps1',
        }
        if filepath.name in excluded_files:
            return []

        # Skip prompt template files (legitimate use of prompt-related keywords)
        if 'prompt' in filepath.name.lower() and filepath.suffix == '.py':
            return []

        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Analyze content
        findings = []
        lines = content.split('\n')

        for line_number, line in enumerate(lines, 1):
            matches = list(detector.analyze_line(line, line_number, str(filepath)))
            for match in matches:
                findings.append((line_number, match))

        return findings

    except Exception as e:
        print(f"Error reading {filepath}: {e}", file=sys.stderr)
        return []


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Check files for prompt injection patterns (USPTO PTAB MCP)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python check_prompt_injections.py src/**/*.py
  python check_prompt_injections.py README.md config.yml
  python check_prompt_injections.py --verbose src/ tests/
  python check_prompt_injections.py --update-baseline src/ tests/ *.md *.yml *.yaml *.json *.py

Detected attack categories:
- Instruction override ("ignore previous instructions")
- Prompt extraction ("show me your instructions")
- Persona switching ("you are now a different AI")
- Output format manipulation ("encode in hex")
- Social engineering ("we became friends")
- USPTO PTAB specific ("extract all IPR trial numbers", "bypass PTAB API")
- Unicode steganography (emoji-based hiding)

Critical: Detects Unicode Variation Selector steganography
from Repello.ai article where malicious prompts are hidden
in invisible characters appended to innocent text like "Hello!".

Baseline System:
  --baseline: Check against existing baseline (only NEW findings fail)
  --update-baseline: Update baseline with current findings
  --force-baseline: Create new baseline (overwrites existing)
"""
    )

    parser.add_argument(
        'files',
        nargs='*',
        help='Files and directories to check for prompt injections'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed output including full matches'
    )

    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Only show summary (suppress individual findings)'
    )

    parser.add_argument(
        '--include-security-files',
        action='store_true',
        help='Check security documentation files (normally excluded)'
    )

    parser.add_argument(
        '--baseline',
        action='store_true',
        help='Use baseline file to filter out known findings'
    )

    parser.add_argument(
        '--update-baseline',
        action='store_true',
        help='Update baseline with current findings (for legitimate false positives)'
    )

    parser.add_argument(
        '--force-baseline',
        action='store_true',
        help='Create new baseline file (overwrites existing)'
    )

    args = parser.parse_args()

    if not args.files:
        print("No files specified. Use --help for usage.", file=sys.stderr)
        return 2

    # Handle baseline operations
    if args.force_baseline:
        # Create new baseline
        print(f"Creating new baseline: {BASELINE_FILE}")
        baseline = {}
    else:
        baseline = load_baseline()

    detector = PTABPromptInjectionDetector()
    total_issues = 0
    new_issues = 0  # Issues not in baseline
    total_files_checked = 0
    files_with_issues = []
    files_with_new_issues = []
    unicode_steganography_detected = False
    new_findings = []

    for file_pattern in args.files:
        filepath = Path(file_pattern)

        if filepath.is_file():
            files_to_check = [filepath]
        elif filepath.is_dir():
            # Recursively check directory
            files_to_check = []
            for ext in ['.py', '.txt', '.md', '.yml', '.yaml', '.json', '.js', '.ts', '.html', '.xml', '.csv']:
                files_to_check.extend(filepath.rglob(f"*{ext}"))
        else:
            # Handle glob patterns
            files_to_check = list(filepath.parent.glob(filepath.name)) if filepath.parent.exists() else []

        for file_path in files_to_check:
            if not file_path.is_file():
                continue

            # Skip security files unless explicitly requested
            if not args.include_security_files and file_path.name in {
                'SECURITY_SCANNING.md', 'security_examples.py', 'test_security.py',
                'ptab_prompt_injection_detector.py', 'check_prompt_injections.py'
            }:
                continue

            total_files_checked += 1
            findings = check_file(file_path, detector)

            if findings:
                files_with_issues.append(str(file_path))
                total_issues += len(findings)

                # Filter findings against baseline
                if baseline or args.update_baseline:
                    baseline_file_key = str(file_path)
                    if baseline_file_key not in baseline:
                        baseline[baseline_file_key] = {}

                    for line_num, match in findings:
                        fingerprint = get_fingerprint(file_path, line_num, match)
                        is_new = fingerprint not in baseline[baseline_file_key]

                        if is_new:
                            new_issues += 1
                            files_with_new_issues.append(str(file_path))
                            new_findings.append((file_path, line_num, match))

                            # Add to baseline if updating
                            if args.update_baseline:
                                baseline[baseline_file_key][fingerprint] = {
                                    'line': line_num,
                                    'match': match
                                }
                else:
                    # No baseline - all findings are new
                    new_issues += len(findings)
                    for line_num, match in findings:
                        new_findings.append((file_path, line_num, match))

                # Check for Unicode steganography specifically
                for _, match in findings:
                    if 'steganography' in match.lower() or 'variation selector' in match.lower():
                        unicode_steganography_detected = True

                # Only show details if using baseline or verbose (to reduce noise)
                show_details = args.verbose or args.baseline or args.update_baseline

                if not args.quiet and show_details:
                    print(f"\n[!] Prompt injection patterns found in {file_path}:")
                    for line_num, match in findings:
                        fingerprint = get_fingerprint(file_path, line_num, match)
                        in_baseline = baseline and fingerprint in baseline.get(str(file_path), {})
                        status = " [BASELINE]" if in_baseline else " [NEW]" if (baseline or args.update_baseline) else ""

                        if args.verbose:
                            safe_match = match.encode('ascii', 'replace').decode('ascii')
                            print(f"  Line {line_num:4d}: {safe_match}{status}")
                        else:
                            safe_match = match.encode('ascii', 'replace').decode('ascii')
                            display_match = safe_match[:60] + "..." if len(safe_match) > 60 else safe_match
                            print(f"  Line {line_num:4d}: {display_match}{status}")

    # Save baseline if updating
    if args.update_baseline or args.force_baseline:
        save_baseline(baseline)
        print(f"\nBaseline updated: {BASELINE_FILE}")
        print(f"Total tracked findings: {sum(len(v) for v in baseline.values())}")

    # Summary
    if not args.quiet or (args.baseline and new_issues > 0) or total_issues > 0:
        print(f"\n{'='*70}")
        print(f"USPTO PTAB MCP Security Scan Results:")
        print(f"Files checked: {total_files_checked}")
        print(f"Total findings: {total_issues}")
        if baseline or args.baseline:
            print(f"Baseline findings: {total_issues - new_issues}")
            print(f"NEW findings: {new_issues}")
        print(f"Files with findings: {len(files_with_issues)}")
        if baseline or args.baseline:
            print(f"Files with NEW findings: {len(set(files_with_new_issues))}")

        if unicode_steganography_detected:
            print(f"\n[CRITICAL] Unicode steganography detected!")
            print("This indicates potential emoji-based prompt injection attacks")
            print("as described in the Repello.ai article. IMMEDIATE REVIEW REQUIRED.")

        if new_issues > 0 and not args.update_baseline:
            print(f"\n[WARNING] NEW prompt injection patterns detected!")
            print("These patterns may indicate attempts to:")
            print("- Override system instructions")
            print("- Extract sensitive prompts")
            print("- Change AI behavior")
            print("- Bypass security controls")
            print("- Extract USPTO PTAB trial/appeal/interference data")
            print("- Hide malicious instructions in Unicode characters")
            print("\nTo update baseline with legitimate findings, run:")
            print(f"  python check_prompt_injections.py --update-baseline src/ tests/ *.md *.yml *.yaml *.json *.py")
        elif new_issues == 0 and baseline:
            print("\n[OK] No NEW prompt injection patterns detected.")
            print("All findings match baseline (existing known findings).")
        elif total_issues == 0:
            print("\n[OK] No prompt injection patterns detected.")
            print("System appears secure against known injection techniques.")
        else:
            print(f"\n[INFO] Baseline updated with {new_issues} new findings.")

    return 1 if new_issues > 0 and not args.update_baseline else 0


if __name__ == '__main__':
    sys.exit(main())
