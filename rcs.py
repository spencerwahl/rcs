from __future__ import division, print_function, unicode_literals

import json, pycouchdb, requests, jsonschema, regparse, db, config, os, logging

from functools import wraps
from logging.handlers import RotatingFileHandler
from flask import Flask, Response, current_app, got_request_exception
from flask.ext.restful import reqparse, request, abort, Api, Resource

app = Flask(__name__)
app.config.from_object(config)
if os.environ.get('RCS_CONFIG'):
    app.config.from_envvar('RCS_CONFIG')
handler = RotatingFileHandler( app.config['LOGFILE'], maxBytes=10000, backupCount=1 )
handler.setLevel( app.config['LOGLEVEL'] )
app.logger.addHandler(handler)
api = Api(app)

client = pycouchdb.Server( app.config['DB_CONN'] )
jsonset = client.database( app.config['DB_NAME'] )
# client[app.config['DB_NAME']].authenticate( app.config['DB_USER'], app.config['DB_PASS'] )
validator = jsonschema.validators.Draft4Validator( json.load(open(app.config['REG_SCHEMA'])) )

def log_exception(sender,exception):
    """Detailed error logging"""
    app.logger.error(
        """
Request:   {method} {path}
IP:        {ip}
Raw Agent: {agent}
        """.format(
            method = request.method,
            path = request.path,
            ip = request.remote_addr,
            agent = request.user_agent.string,
        ), exc_info=exception
    )
got_request_exception.connect(log_exception, app)

def jsonp(func):
    """Wraps JSONified output for JSONP requests."""
    @wraps(func)
    def decorated_function(*args, **kwargs):
        callback = request.args.get('callback', False)
        if callback:
            data = str(func(*args, **kwargs).data)
            content = str(callback) + '(' + data + ')'
            mimetype = 'application/javascript'
            return current_app.response_class(content, mimetype=mimetype)
        else:
            return func(*args, **kwargs)
    return decorated_function

def make_id( key, lang ):
    return "{0}.{1}.{2}".format('rcs',key,lang)

def get_doc( smallkey, lang ):
    try:
        o = jsonset.get(smallkey)
    except pycouchdb.exceptions.NotFound as nfe:
        print( nfe )
        return None
    if o is not None:
        fragment = o.get('data',{}).get(lang,None)
        if fragment is not None:
            result = { 'layers': {} }
            result['layers'][ o['type'] ] = [ fragment ]
            return result
    return None

class Doc(Resource):
    def get(self, lang, smallkey):
        doc = get_doc( smallkey, lang )
        print( doc )
        if doc is None:
            return None,404
        return Response(json.dumps(doc),  mimetype='application/json')

class Docs(Resource):
    @jsonp
    def get(self, lang, smallkeylist):
        keys = [ x.strip() for x in smallkeylist.split(',') ]
        docs = [ get_doc(smallkey,lang) for smallkey in keys ]
        print( docs )
        return Response(json.dumps(docs),  mimetype='application/json')

class Register(Resource):
    def get(self,smallkey):
        raise Exception('broken')

    def put(self, smallkey):
        try:
            s = json.loads( request.data )
        except Exception:
            return '{"errors":["Unparsable json"]}',400
        if not validator.is_valid( s ):
            resp = { 'errors': [x.message for x in validator.iter_errors(s)] }
            print( resp )
            return Response(json.dumps(resp),  mimetype='application/json', status=400)

        data = dict( key=smallkey )
        if s['payload_type'] == 'wms':
            data['en'] = regparse.wms.make_node( s['en'], make_id(smallkey,'en') )
            data['fr'] = regparse.wms.make_node( s['fr'], make_id(smallkey,'fr') )
        else:
            data['en'] = regparse.esri_feature.make_node( s['en'], make_id(smallkey,'en') )
            data['fr'] = regparse.esri_feature.make_node( s['fr'], make_id(smallkey,'fr') )

        print( data )
        try:
            jsonset.delete( smallkey )
        except pycouchdb.exceptions.NotFound as nfe:
            pass
        jsonset.save( { '_id':smallkey, 'type':s['payload_type'], 'data':data } )
        app.logger.info( 'added a smallkey %s' % smallkey )
        return smallkey, 201

    def delete(self, smallkey):
        jsonset.remove( smallkey )
        app.logger.info( 'removed a smallkey %s' % smallkey )
        return '', 204


api.add_resource(Doc, '/doc/<string:lang>/<string:smallkey>')
api.add_resource(Docs, '/docs/<string:lang>/<string:smallkeylist>')
api.add_resource(Register, '/register/<string:smallkey>')

if __name__ == '__main__':
    app.run(debug=True)
