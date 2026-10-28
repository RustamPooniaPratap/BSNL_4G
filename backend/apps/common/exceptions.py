"""Consistent JSON error responses for every API endpoint.

Every error body has the shape ``{"error": "<message>", "details": {...}}``.
Unexpected exceptions are logged server-side and returned as a generic 500 so
that stack traces and filesystem paths never reach the browser.
"""
import logging

from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


class ServiceUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'The reporting data source is unavailable.'
    default_code = 'service_unavailable'

    def __init__(self, detail=None, error_code: str = 'service_unavailable'):
        super().__init__(detail)
        self.error_code = error_code


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        view = context.get('view')
        logger.exception('Unhandled error in %s', type(view).__name__ if view else 'API view')
        return Response(
            {'error': 'An unexpected server error occurred.', 'details': {}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, ValidationError):
        details = response.data if isinstance(response.data, dict) else {'non_field_errors': response.data}
        response.data = {'error': 'Invalid request parameters.', 'details': details}
    else:
        detail = response.data.get('detail', str(exc)) if isinstance(response.data, dict) else str(exc)
        error_code = getattr(exc, 'error_code', None)
        response.data = {'error': str(detail), 'details': {'code': error_code} if error_code else {}}
    return response
