import os
from pathlib import Path

from e2b_code_interpreter import Sandbox


LOCAL_VCF = Path("/AI-Assistant/sample_test.vcf")
REMOTE_VCF = "/home/user/uploads/sample_test.vcf"


def main():
    api_key = os.getenv("E2B_API_KEY") or os.getenv("E2B_Sandbox_KEY")
    print(f"key_present={bool(api_key)}")
    print(f"local_exists={LOCAL_VCF.exists()}")
    print(f"local_bytes={LOCAL_VCF.stat().st_size if LOCAL_VCF.exists() else 0}")

    sandbox = Sandbox.create(
        template="code-interpreter-v1",
        timeout=300,
        api_key=api_key,
    )
    print(f"sandbox_id={sandbox.sandbox_id}")

    try:
        sandbox.files.write(REMOTE_VCF, LOCAL_VCF.read_text())
        code = f"""
from pathlib import Path

path = Path("{REMOTE_VCF}")
variant_count = 0
samples = []
missing = 0
genotypes = 0

for line in path.read_text().splitlines():
    if line.startswith("#CHROM"):
        cols = line.split("\\t")
        samples = cols[9:]
    elif line and not line.startswith("#"):
        variant_count += 1
        cols = line.split("\\t")
        for sample in cols[9:]:
            gt = sample.split(":", 1)[0]
            genotypes += 1
            if gt in {{"./.", ".", ".|."}}:
                missing += 1

print(f"samples={{len(samples)}}")
print(f"variants={{variant_count}}")
print(f"genotypes={{genotypes}}")
print(f"missing_genotypes={{missing}}")
print(f"missingness={{missing / genotypes if genotypes else 0:.4f}}")
"""
        result = sandbox.run_code(code, timeout=60)
        print(f"stdout={result.logs.stdout if result.logs else []}")
        print(f"stderr={result.logs.stderr if result.logs else []}")
        print(f"error={result.error}")
    finally:
        sandbox.kill()


if __name__ == "__main__":
    main()
