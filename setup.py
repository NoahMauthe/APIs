from setuptools import setup, find_packages

setup(name='API',

version='1.0',

description='API for Google Play and F-Droid',

url='https://github.com/NoahMauthe/APIs',

author='Noah Mauthe',

author_email='s8nomaut@stud.uni-saarland.de',

license='MIT',

packages=find_packages(),

install_requires=['certifi',
'cffi',
'chardet',
'cryptography',
'idna',
'protobuf',
'pycparser',
'requests',
'six',
'toml',
'urllib3'],

package_data={

        # If any package contains *.txt or *.rst files, include them:

        "": ["*.txt", "*.toml", 'resources/devices.toml'],
        },


zip_safe=False)




