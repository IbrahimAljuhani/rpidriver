from setuptools import setup, find_packages

from rpidriver.__version__ import __version__

try:
    with open("README.md", "r", encoding="utf-8") as f:
        long_description = f.read()
except FileNotFoundError:
    long_description = "Smart hardware proxy for Odoo POS — built for Raspberry Pi"

setup(
    name="rpidriver",
    version=__version__,
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
            "static/css/*.css",
            "translations/*/LC_MESSAGES/*.po",
            "translations/*/LC_MESSAGES/*.mo",
        ],
    },
    install_requires=[
        "Flask>=2.3",
        "Flask-Babel>=4.0,<5.0",
        "Flask-Cors>=4.0,<5.0",
        "pyserial>=3.5",
        "Pillow>=10.0",
        "arabic-reshaper>=3.0",
        "python-bidi>=0.4.2,<0.7",
        "pyusb>=1.2",
        "requests>=2.28",
    ],
    extras_require={
        # pip install rpidriver[neoleap]
        "neoleap": ["websocket-client>=1.6"],
        # pip install rpidriver[cups]  (Linux only — requires libcups2-dev)
        "cups": ["pycups>=2.0"],
        # pip install rpidriver[dev]
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
