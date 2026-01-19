#!/usr/bin/env python3
"""
Quick verification script for PTAB proxy server.

Tests:
1. Standalone mode (local proxy on port 8083)
2. PFW detection
3. Health check
4. Enhanced filename generation
"""

import asyncio
import httpx
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ptab_mcp.main import get_local_proxy_port, _detect_pfw_proxy
from ptab_mcp.proxy.server import generate_enhanced_filename, sanitize_description


def test_safe_port_parsing():
    """Test 1: Safe port parsing."""
    print("\n" + "="*60)
    print("TEST 1: Safe Port Parsing")
    print("="*60)

    # Test with environment variable
    os.environ['PTAB_PROXY_PORT'] = '8083'
    port = get_local_proxy_port()
    print(f"[PASS] PTAB_PROXY_PORT=8083 -> {port}")
    assert port == 8083

    # Test with "none" sentinel
    os.environ['PTAB_PROXY_PORT'] = 'none'
    port = get_local_proxy_port()
    print(f"[PASS] PTAB_PROXY_PORT=none -> {port} (default)")
    assert port == 8083

    # Test with invalid value
    os.environ['PTAB_PROXY_PORT'] = 'invalid'
    port = get_local_proxy_port()
    print(f"[PASS] PTAB_PROXY_PORT=invalid -> {port} (fallback)")
    assert port == 8083

    # Clean up
    if 'PTAB_PROXY_PORT' in os.environ:
        del os.environ['PTAB_PROXY_PORT']

    print("[PASS] All safe port parsing tests passed!")


def test_pfw_detection():
    """Test 2: PFW proxy detection."""
    print("\n" + "="*60)
    print("TEST 2: PFW Proxy Detection")
    print("="*60)

    # Test with "none" sentinel (instant startup)
    os.environ['CENTRALIZED_PROXY_PORT'] = 'none'
    result = _detect_pfw_proxy()
    print(f"[PASS] CENTRALIZED_PROXY_PORT=none -> {result} (skipped detection)")
    assert result is None

    # Test with actual detection
    if 'CENTRALIZED_PROXY_PORT' in os.environ:
        del os.environ['CENTRALIZED_PROXY_PORT']

    print("\n[INFO] Attempting to detect PFW proxy...")
    result = _detect_pfw_proxy()

    if result:
        print(f"[PASS] PFW proxy detected on port {result}")
    else:
        print("[INFO] PFW proxy not detected (standalone mode)")

    print("[PASS] PFW detection test completed!")


async def test_health_check():
    """Test 3: Proxy health check."""
    print("\n" + "="*60)
    print("TEST 3: Proxy Health Check")
    print("="*60)

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            # Test local proxy (if running)
            local_port = 8083
            try:
                response = await client.get(f"http://localhost:{local_port}/")
                if response.status_code == 200:
                    data = response.json()
                    print(f"[PASS] Local proxy responding on port {local_port}")
                    print(f"   Service: {data.get('service')}")
                    print(f"   Status: {data.get('status')}")
                else:
                    print(f"[WARN] Local proxy returned status {response.status_code}")
            except Exception as e:
                print(f"[INFO] Local proxy not running on port {local_port}")

            # Test PFW proxy (if running)
            pfw_port = 8080
            try:
                response = await client.get(f"http://localhost:{pfw_port}/")
                if response.status_code == 200:
                    data = response.json()
                    print(f"[PASS] PFW proxy responding on port {pfw_port}")
                    print(f"   Service: {data.get('service')}")
                    print(f"   Status: {data.get('status')}")
                else:
                    print(f"[WARN] PFW proxy returned status {response.status_code}")
            except Exception as e:
                print(f"[INFO] PFW proxy not running on port {pfw_port}")

        print("[PASS] Health check test completed!")

    except Exception as e:
        print(f"[FAIL] Health check failed: {e}")


def test_enhanced_filenames():
    """Test 4: Enhanced filename generation."""
    print("\n" + "="*60)
    print("TEST 4: Enhanced Filename Generation")
    print("="*60)

    # Test 1: Full information
    filename = generate_enhanced_filename(
        filing_date="2024-05-15",
        identifier="IPR2024-00123",
        patent_number="8524787",
        document_description="Final Written Decision",
        document_code="FWD"
    )
    print(f"[PASS] Full info: {filename}")
    assert "PTAB-2024-05-15" in filename
    assert "IPR2024-00123" in filename
    assert "PAT-8524787" in filename
    assert "FINAL_WRITTEN_DECISION" in filename

    # Test 2: No patent number
    filename = generate_enhanced_filename(
        filing_date="2024-05-15",
        identifier="CBM2024-00045",
        patent_number=None,
        document_description="Institution Decision"
    )
    print(f"[PASS] No patent: {filename}")
    assert "PAT-" not in filename

    # Test 3: No filing date
    filename = generate_enhanced_filename(
        filing_date=None,
        identifier="PGR2024-00001",
        patent_number="10234567",
        document_description="Patent Owner Response"
    )
    print(f"[PASS] No date: {filename}")
    assert "PTAB-UNKNOWN" in filename

    # Test 4: Special characters in description
    filename = generate_enhanced_filename(
        filing_date="2024-01-10",
        identifier="IPR2024-00456",
        patent_number="9876543",
        document_description="Petitioner's Sur-Reply (Updated)",
        document_code="PSR"
    )
    print(f"[PASS] Special chars: {filename}")
    assert filename.endswith(".pdf")
    # Should have sanitized description
    assert "PETITIONERS" in filename

    print("[PASS] All enhanced filename tests passed!")


def main():
    """Run all verification tests."""
    print("\n" + "="*60)
    print("PTAB PROXY SERVER VERIFICATION")
    print("="*60)

    try:
        # Run synchronous tests
        test_safe_port_parsing()
        test_pfw_detection()
        test_enhanced_filenames()

        # Run async test
        asyncio.run(test_health_check())

        # Summary
        print("\n" + "="*60)
        print("VERIFICATION SUMMARY")
        print("="*60)
        print("[PASS] Safe port parsing: PASSED")
        print("[PASS] PFW detection: PASSED")
        print("[PASS] Enhanced filenames: PASSED")
        print("[PASS] Health checks: COMPLETED")
        print("\n[SUCCESS] All verification tests passed!")
        print("="*60)

    except AssertionError as e:
        print(f"\n[FAIL] Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] Verification error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
