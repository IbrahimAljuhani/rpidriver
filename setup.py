from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

with open("requirements.txt") as f:
    install_requires = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="rpidriver",
    version="1.0.0",
    author="Ibrahim Aljuhani",
    author_email="info@ia.sa",
    description="Smart hardware proxy for Odoo POS — built for Raspberry Pi",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ibrahimaljuhani/rpidriver",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "rpidriver": [
            "templates/*.html",
            "translations/*/LC_MESSAGES/*.po",
            "translations/*/LC_MESSAGES/*.mo",
        ],
    },
    install_requires=install_requires,
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=4.0",
        ],
    },
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "rpidriver=rpidriver:main",
        ],
    },
    classifiers=[
        "License :: OSI Approved :: GNU Affero General Public License v3",
        "Programming Language :: Python :: 3",
        "Operating System :: POSIX :: Linux",
        "Topic :: Office/Business :: Financial :: Point-Of-Sale",
    ],
    license="AGPL-3.0",
)
