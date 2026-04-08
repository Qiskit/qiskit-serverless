# Gateway REST API Documentation

Succinct documentation for the Qiskit Serverless Gateway REST API.

## Production URL

**Base URL**: https://qiskit-serverless.quantum.ibm.com/api/v1/

## Quick Links

- **OpenAPI Schema (JSON)**: https://qiskit-serverless.quantum.ibm.com/swagger.json
- **OpenAPI Schema (YAML)**: https://qiskit-serverless.quantum.ibm.com/swagger.yaml

## Documentation Structure

- **index.rst** - Quick start and overview
- **authentication.rst** - Authentication guide
- **endpoints.rst** - Complete endpoint reference

## Building Documentation

```bash
cd docs
pip install -r requirements-doc.txt
make html
```

Or use tox:

```bash
tox -e docs
```

## Contributing

When adding new endpoints, use the `@swagger_auto_schema` decorator:

```python
from drf_yasg.utils import swagger_auto_schema

@swagger_auto_schema(
    operation_description="Brief description",
    responses={200: MySerializer}
)
@api_view(["GET"])
def my_endpoint(request):
    pass