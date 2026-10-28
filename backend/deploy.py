import os
import shutil
import zipfile
import subprocess


def main():
    print("Creating Lambda deployment package...")

    # Clean previous package
    shutil.rmtree("lambda-package", ignore_errors=True)

    if os.path.exists("lambda-deployment.zip"):
        os.remove("lambda-deployment.zip")

    os.makedirs("lambda-package")

    # Install dependencies inside Lambda's Linux environment.
    # pip installs into the container's own /tmp (fast), then the finished
    # tree is copied once onto the mounted folder. Writing thousands of small
    # files straight onto the Windows bind mount is very slow.
    print("Installing dependencies...")

    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{os.getcwd()}:/var/task",
            "--platform",
            "linux/amd64",
            "--entrypoint",
            "",
            "public.ecr.aws/lambda/python:3.12",
            "/bin/sh",
            "-c",
            "pip install --target /tmp/pkg -r /var/task/requirements.txt "
            "--no-compile --disable-pip-version-check --quiet "
            "&& cp -r /tmp/pkg/. /var/task/lambda-package/",
        ],
        check=True,
    )

    # Copy your application files
    print("Copying application files...")

    for file in [
        "server.py",
        "lambda_handler.py",
        "context.py",
        "resources.py",
    ]:
        if os.path.exists(file):
            shutil.copy2(file, "lambda-package/")

    # Copy data folder
    if os.path.exists("data"):
        shutil.copytree("data", "lambda-package/data")

    # Create ZIP
    print("Creating ZIP...")

    with zipfile.ZipFile("lambda-deployment.zip", "w", zipfile.ZIP_DEFLATED) as zipf:

        for root, dirs, files in os.walk("lambda-package"):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for file in files:
                if file.endswith(".pyc"):
                    continue
                file_path = os.path.join(root, file)

                # Put everything at the root of the ZIP
                arcname = os.path.relpath(file_path, "lambda-package")

                zipf.write(file_path, arcname)

    size_mb = os.path.getsize("lambda-deployment.zip") / (1024 * 1024)

    print(f"Created lambda-deployment.zip ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
