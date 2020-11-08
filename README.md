[![Build Status](https://travis-ci.com/ladybug-tools/pydantic-openapi-helper.svg?branch=master)](https://travis-ci.com/ladybug-tools/pydantic-openapi-helper)

[![Python 3.7](https://img.shields.io/badge/python-3.7-blue.svg)](https://www.python.org/downloads/release/python-370/)

# pydantic-openapi-helper

A small module to add additional post-processing to the OpenAPI schemas that are generated
by Pydantic.

This module is designed to work with Ladybug Tools schema libraries such as
[honeybee-schema](https://github.com/ladybug-tools/honeybee-schema/),
[dragonfly-schema](https://github.com/ladybug-tools/dragonfly-schema/) and
[queenbee](https://github.com/ladybug-tools/queenbee/) but might be also helpful for
other projects.

The most important feature of the library is to generate an OpenAPI schema to use
polymorphism. It adds referenced values to subclasses using allOf field as explained in
this post: https://swagger.io/docs/specification/data-models/inheritance-and-polymorphism

We are not intending to support the development for make this library work universally
but you are more than welcome to fork and make your own version of the library.


## installation

`python3 -m pip install pydantic-openapi-helper`
