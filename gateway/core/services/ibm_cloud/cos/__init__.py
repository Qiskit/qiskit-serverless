"""IBM Cloud Object Storage client module."""

from core.services.ibm_cloud.cos.cos_client import COSClient, CosHmacCredentials

__all__ = ["COSClient", "CosHmacCredentials"]
