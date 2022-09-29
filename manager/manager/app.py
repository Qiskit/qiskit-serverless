""" Application definition"""
# pylint: disable=keyword-arg-before-vararg
import logging
import sys
import re
import importlib
from flask import Flask
from flask_restx import Api, Resource, fields
from werkzeug.middleware.proxy_fix import ProxyFix
from manager.errors import ValidationError, NotFoundError, ConfigurationError


app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)
api = Api(
    app,
    version="1.0",
    title="Quantum Serverless API",
    description="API for cluster management",
)
app.config.from_object("manager.config.ProductionConfig")


ns = api.namespace("quantum-serverless-middleware", description="Cluster operations")

logging.basicConfig(filename="debug.log", level=logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)

log = logging.getLogger("cluster_dao")

cluster_model = api.model(
    "Cluster",
    {
        "name": fields.String(required=True, description="The cluster name"),
    },
)
cluster_detail_model = api.model(
    "ClusterDetail",
    {
        "name": fields.String(required=True, description="The cluster name"),
        "host": fields.String(required=True, description="The cluster host"),
        "port": fields.Integer(required=True, description="The cluster port"),
        "ip": fields.String(required=True, description="The cluster password"),
    },
)


def validate(payload):
    """
    Validate input for cluster creation
    Args:
        payload: pyload for insert cluster API

    Raise:
        ValidationError
    """
    cluster_name_validator_pattern = (
        "^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$"
    )
    cluster_name_max_length = 53
    re.compile(cluster_name_validator_pattern)
    if not re.fullmatch(cluster_name_validator_pattern, payload["name"]):
        log.info(
            "ValidationError for %s. Custer name may contain small letters, digits and -.",
            payload["name"],
        )
        raise ValidationError("Custer name may contain small letters, digits and -.")
    if len(payload["name"]) > cluster_name_max_length:
        log.info(
            "ValidationError for %s. Custer name may have maximum %d characters.",
            payload["name"],
            cluster_name_max_length,
        )
        raise ValidationError(
            "Custer name may have maximum "
            + str(cluster_name_max_length)
            + "characters."
        )


@api.errorhandler(ValidationError)
def handle_validation_exception(error):
    """Return a error message and 400 status code"""
    return {"message": str(error)}, 400


@api.errorhandler(NotFoundError)
def handle_not_found_exception(error):
    """Return a error message and 500 status code"""
    return {"message": str(error)}, 404


@api.errorhandler(Exception)
def handle_general_exception(error):
    """Return a error message and 500 status code"""
    return {"message": str(error)}, 500


@ns.route("/cluster/")
class ClusterList(Resource):
    """Shows a list of all clusters, and lets you POST to add new clusters"""

    def __init__(self, apy=None, *args, **kwargs):
        super().__init__(apy, args, kwargs)
        self.dao = None

    def get_cluster_dao_instance(self):
        """
        Initialize cluster dao if necessary and returns the instance.

        Returns:
            ClusterDAO
        """
        if self.dao is None:
            dao_factory = app.config.get("CLUSTER_DAO_FACTORY")
            namespace = app.config.get("NAMESPACE")
            if namespace is None:
                raise ConfigurationError()
            module = importlib.import_module(dao_factory[0 : dao_factory.rindex(".")])
            class_ = getattr(module, dao_factory[dao_factory.rindex(".") + 1 :])
            instance = class_.create_instance(self, namespace)
            self.dao = instance
        return self.dao

    @ns.doc("list_clusters")
    @ns.marshal_list_with(cluster_model)
    def get(self):
        """List all clusters"""
        return self.get_cluster_dao_instance().get_all()

    @ns.doc("create_cluster")
    @ns.expect(cluster_model)
    @ns.marshal_with(cluster_model, code=201)
    def post(self):
        """Create a new cluster"""
        validate(api.payload)
        return self.get_cluster_dao_instance().create(api.payload), 201


@ns.route("/cluster/<name>")
@ns.response(404, "Cluster not found")
@ns.param("name", "The cluster identifier - name")
class Cluster(Resource):
    """Show a single cluster item and lets you delete them"""

    def __init__(self, apy=None, *args, **kwargs):
        super().__init__(apy, args, kwargs)
        self.dao = None

    def get_cluster_dao_instance(self):
        """
        Initialize cluster dao if necessary and returns the instance.

        Returns:
            ClusterDAO
        """
        if self.dao is None:
            dao_factory = app.config.get("CLUSTER_DAO_FACTORY")
            namespace = app.config.get("NAMESPACE")
            if namespace is None:
                raise ConfigurationError()
            module = importlib.import_module(dao_factory[0 : dao_factory.rindex(".")])
            class_ = getattr(module, dao_factory[dao_factory.rindex(".") + 1 :])
            instance = class_.create_instance(self, namespace)
            self.dao = instance
        return self.dao

    @ns.doc("get_cluster")
    @ns.marshal_with(cluster_detail_model)
    def get(self, name):
        """Fetch a given resource"""
        return self.get_cluster_dao_instance().get(name)

    @ns.doc("delete_cluster")
    @ns.response(204, "Cluster deleted")
    def delete(self, name):
        """Delete a cluster given its identifier"""
        self.get_cluster_dao_instance().delete(name)
        return "", 204


if __name__ == "__main__":
    app.run(debug=True)
