import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.action_manager.backends import DockerBackend


def main():
    backend = DockerBackend()
    result = backend.run(
        """
from pathlib import Path

vcf_path = Path("/home/user/uploads/sample_test.vcf")
variant_count = 0
samples = []
missing = 0
genotypes = 0

for line in vcf_path.read_text().splitlines():
    if line.startswith("#CHROM"):
        samples = line.split("\\t")[9:]
    elif line and not line.startswith("#"):
        variant_count += 1
        for sample in line.split("\\t")[9:]:
            gt = sample.split(":", 1)[0]
            genotypes += 1
            if gt in {"./.", ".", ".|."}:
                missing += 1

print("docker smoke ok")
print(f"samples={len(samples)}")
print(f"variants={variant_count}")
print(f"genotypes={genotypes}")
print(f"missing_genotypes={missing}")
print(f"missingness={missing / genotypes if genotypes else 0:.4f}")
""",
        uploaded_files=[
            {
                "filename": "sample_test.vcf",
                "local_path": "/AI-Assistant/sample_test.vcf",
                "sandbox_path": "/home/user/uploads/sample_test.vcf",
            }
        ],
        timeout=60,
    )
    print(result)


if __name__ == "__main__":
    main()
