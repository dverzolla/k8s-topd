from setuptools import setup, find_packages

setup(
    name="k8s-topd",
    version="0.1.0",
    author="David Verzolla",
    author_email="dverzolla@gmail.com",
    description="A CLI tool for Kubernetes top which measures resource usage of pods and nodes, also ephemeral disk usage.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/dverzolla/k8s-topd",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
    install_requires=[
        "requests",
        "charset-normalizer",
        "idna",
        "urllib3",
    ],
    entry_points={
        "console_scripts": [
            "k8s-topd=kubectl-topd:main",
        ],
    },
)