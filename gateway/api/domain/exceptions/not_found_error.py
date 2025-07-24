# myapp/exceptions.py

class NotFoundError(Exception):
    """Excepción base para errores de dominio de negocio."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)