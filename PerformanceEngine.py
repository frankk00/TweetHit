# Copyright (C) 2011 O. Can Bascil <ocanbascil at gmail com>
#
# This program is release under the BSD License. You can find the full text of
# the license in the LICENSE file.
"""
PerformanceEngine
==============================
    PerformanceEngine is a simple wrapper module that enables layered 
    data model storage in Google Application Engine.
    
    It can store/retrieve models using local cache, memcache or datastore.
    
    You can also retrieve results in different formats (list,key-model dict,
    key_name-model dict)
    
    Its main goal is to increase both application and developer performance.
    


    The Product Advertising API provides programmatic access to Amazon's
    product selection and discovery functionality so that developers like you
    can advertise Amazon products to monetize your website.
    
    The Product Advertising API helps you advertise Amazon products using
    product search and look up capability, product information and features
    such as Customer Reviews, Similar Products, Wish Lists and New and Used
    listings. You can make money using the Product Advertising API to advertise
    Amazon products in conjunction with the Amazon Associates program. Be sure
    to join the Amazon Associates program to earn up to 15% in referral fees
    when the users you refer to Amazon sites buy qualifying products.  


Requirements
------------
cachepy => http://appengine-cookbook.appspot.com/recipe/cachepy-faster-than-memcache-and-unlimited-quota/


License
-------

This program is release under the BSD License. You can find the full text of
the license in the LICENSE file.

"""
from google.appengine.api import memcache
from google.appengine.ext import db
from google.appengine.api import datastore
from google.appengine.datastore import entity_pb

import cachepy
import logging

'''Constants for storage levels'''
DATASTORE = 'datastore'
MEMCACHE = 'memcache'
LOCAL = 'local'
ALL_LEVELS = [DATASTORE,MEMCACHE,LOCAL]

'''Constants for result types'''
LIST = 'list'
DICT = 'dict'
KEY_NAME_DICT = 'key_name_dict'

LOCAL_EXPIRATION = 0
MEMCACHE_EXPIRATION = 0

none_filter  = lambda dict : [k for k,v in dict.iteritems() if v is None]

def validate_storage(storage_list):
  for storage in storage_list:
    if storage not in ALL_LEVELS:
      raise StorageLayerError(storage)

def key_str(param):
  '''Utility function that extracts a string key from a model or key instance'''
  try:
    return str(db._coerce_to_key(param))
  except db.BadArgumentError:
    raise KeyParameterError(param)
  
def id_or_name(key_str):
  key = db.Key(key_str)
  return key.name() or str(key.id())

def _diff(list1,list2):
  '''Finds the difference of keys between 2 lists
  Used for layered model retrieval'''
  return list(set(list1)-set(list2))

def _to_list(param): 
    if not type(param).__name__=='list':
        result = []
        result.append(param)
    else:
        result = list(param)
    return result

def _to_dict(models):
  '''Utility method to create identifier:model dictionary'''
  result = {}
  for model in models:
    result[key_str(model)] = model
  return result

def serialize(models):
  '''Improve memcache performance converting to protobuf'''
  if models is None:
    return None
  elif isinstance(models, db.Model):
    # Just one instance
    return db.model_to_protobuf(models).Encode()
  else:
    # A list
    return [db.model_to_protobuf(x).Encode() for x in models]

def deserialize(data):
  '''Improve memcache performance by converting from protobuf'''
  if data is None:
    return None
  elif isinstance(data, str):
    # Just one instance
    return db.model_from_protobuf(entity_pb.EntityProto(data))
  else:
    return [db.model_from_protobuf(entity_pb.EntityProto(x)) for x in data]

def _cachepy_get(keys):
  '''Get items with given keys from local cache
  
  Args:
    keys: String representation of db.Keys
  
  Returns:
    Dictionary of key,model pairs in which keys are 
    string representation of db.Key instances
  '''
  result = {}
  for key in keys:
    result[key] = cachepy.get(key)
  return result

def _cachepy_put(models,time = 0):
  '''Put given models to local cache in serialized form
   with expiration in seconds
  
  Args:
    models: List of models to be saved to local cache
    time: Expiration time in seconds for each model instance
  
  Returns:
    List of string representations of db.Keys 
    of the models that were put
    
    If no model is found for given key, value for that key
    in result is set to None
  '''
  to_put = _to_dict(models)
  if time == 0: #cachepy uses None as unlimited caching flag
    time = None
  
  for key, model in to_put.iteritems():
    cachepy.set(key,model,time)
  return to_put.keys()

def _cachepy_delete(keys):
  '''Delete models with given keys from local cache'''
  for key in keys: 
      cachepy.delete(key)

def _memcache_get(keys):
  '''Get items with given keys from memcache
  
  Args:
    keys: List of string representation of db.Keys
  
  Returns:
    Dictionary of key,model pairs in which keys are 
    string representation of db.Key instances
    
    If no model is found for given key, value for that key
    in result is set to None
  '''
  cache_results = memcache.get_multi(keys)
  result = {}
  for key in keys:
    try:
      result[key] = deserialize(cache_results[key])
    except KeyError:
      result[key] = None
  return result
    
def _memcache_put(models,time = 0):
  '''Put given models to memcache in serialized form
   with expiration in seconds
  
  Args:
    models: List of models to be saved to local cache
    time: Expiration time in seconds for each model instance
  
  Returns:
    List of string representations of db.Keys 
    of the models that were put
  '''         
  to_put = _to_dict(models)
        
  for key,model in to_put.iteritems():
      to_put[key] = serialize(model)
          
  memcache.set_multi(to_put,time)
  return to_put.keys()

def _memcache_delete(keys): #Seconds for lock?
  '''Delete models with given keys from memcache'''
  memcache.delete_multi(keys)
  
  
class pdb(object):
  '''Wrapper class for google.appengine.ext.db with seamless cache support'''
  
  @classmethod
  def get(cls,keys,_storage = ALL_LEVELS,_result_type=LIST,**kwds):
    """Fetch the specific Model instance with the given key from given storage layers.
  
    Args:
      _storage: string or array of strings for target storage layers  
      
      Inherited:
        keys: Key within datastore entity collection to find; or string key;
          or list of Keys or string keys.
        config: datastore_rpc.Configuration to use for this request.
      
    Returns:
      If a single key was given: a Model instance associated with key
      for if it exists in the datastore, otherwise None; if a list of
      keys was given: a list whose items are either a Model instance or
      None.
    """
    _storage = _to_list(_storage)
    validate_storage(_storage)
    
    keys = map(key_str, _to_list(keys))
    old_keys = keys
    result = []
    models = {}
    
    if LOCAL in _storage:
        models = dict(models,**_cachepy_get(keys))
        keys = none_filter(models)
          
    if MEMCACHE in _storage and len(keys):
        models = dict(models,**_memcache_get(keys))
        keys = none_filter(models)
    
    if DATASTORE in _storage and len(keys):
        db_results = [model for model in db.get(keys) if model is not None]
        if len(db_results):
          models  = dict(models,**_to_dict(db_results))
    
    if _result_type == LIST:
      #Restore the order of entities   
      for key in old_keys:
        try:
          result.append(models[key])
        except KeyError:
          result.append(None)   
      #Normalized result
      if len(result) > 1:
        return result
      return result[0]
    elif _result_type == DICT:
      return models
    elif _result_type == KEY_NAME_DICT:
      result = {}
      for k,v in models.iteritems():
        result[id_or_name(k)] = v
      return result
    else:
      raise ResultTypeError(_result_type)
        

  @classmethod
  def put(cls,models,_storage = ALL_LEVELS,
                      _local_expiration = LOCAL_EXPIRATION,
                      _memcache_expiration = MEMCACHE_EXPIRATION,
                       **kwds):
    '''Saves models into given storage layers and returns their keys
    
    If the models are written for the first time and they have no keys ,
    They are first written into datastore and then saved to other storage layers
    using the keys returned by datastore put() operation.
    
    Args:

      _storage: string or array of strings for target storage layers  
      _local_expiration: Time in seconds for local cache expiration for models
      _memcache_expiration: Time in seconds for memcache expiration for models
    
      Inherited:
          models: Model instance or list of Model instances.
          config: datastore_rpc.Configuration to use for this request.
    
    Returns:
      A Key or a list of Keys (corresponding to the argument's plurality).
    
    Raises:
      IdentifierNotFoundError if models with no valid identifiers 
      are written into cache storage only
    
      Inherited:
        TransactionFailedError if the data could not be committed.
    '''

    keys = [] 
    models = _to_list(models)   
    _storage = _to_list(_storage)
    validate_storage(_storage)
    
    try: 
      _to_dict(models)
    except db.NotSavedError:
      if DATASTORE in _storage:
        keys = db.put(models)
        models = db.get(keys)
        _storage.remove(DATASTORE)
        if len(_storage):
          return pdb.put(models,_storage,**kwds)
      else: 
        raise IdentifierNotFoundError() 
    
    if DATASTORE in _storage:
      keys = db.put(models)
      
    if LOCAL in _storage:
      keys = _cachepy_put(models, _local_expiration)

    if MEMCACHE in _storage:
      keys = _memcache_put(models,_memcache_expiration)
      
    return keys


  @classmethod
  def delete(cls,keys,_storage = ALL_LEVELS):
    """Delete one or more Model instances from given storage layers
  
    Args:
      _storage: string or array of strings for target storage layers
      
      Inherited:
        models: Model instance, key, key string or iterable thereof.
        config: datastore_rpc.Configuration to use for this request.
  
    """
    keys = map(key_str, _to_list(keys))
    _storage = _to_list(_storage)
    validate_storage(_storage)  
    
    if DATASTORE in _storage:
      db.delete(keys)
      
    if LOCAL in _storage:
      _cachepy_delete(keys)

    if MEMCACHE in _storage:
      _memcache_delete(keys)
  
  
  class Model(db.Model):
    '''Wrapper class for db.Model
    Adds cached storage support to common functions'''
    
    def put(self,**kwds):
      return pdb.put(self, **kwds)
    
    @classmethod
    def get(cls,keys,**kwds):
      return pdb.get(keys,**kwds)
    
    def delete(self,_storage = ALL_LEVELS):
      pdb.delete(self.key(),_storage)
    
    @classmethod
    def get_by_key_name(cls,key_names, parent=None,**kwds):
      """Get instance of Model class by its key's name from the given storage layers.
  
      Args:
        _storage: string or array of strings for target storage layers
        
        Inherited:
          key_names: A single key-name or a list of key-names.
          parent: Parent of instances to get.  Can be a model or key.
      """
      try:
        parent = db._coerce_to_key(parent)
      except db.BadKeyError, e:
        raise db.BadArgumentError(str(e))
      
      key_names = _to_list(key_names)
      key_strings = [key_str(db.Key.from_path(cls.kind(), name, parent=parent))
        for name in key_names]

      return pdb.get(key_strings,**kwds)
    
    @classmethod
    def get_by_id(cls, ids, parent=None,**kwds):
      """Get instance of Model class by id from the given storage layers.
  
      Args:
         _storage: string or array of strings for target storage layers
         
        Inherited:
          ids: A single id or a list of ids.
          parent: Parent of instances to get.  Can be a model or key.
      """
      try:
        parent = db._coerce_to_key(parent)
      except db.BadKeyError, e:
        raise db.BadArgumentError(str(e))
      
      ids = _to_list(ids)
      key_strings = [key_str(datastore.Key.from_path(cls.kind(), id, parent=parent))
        for id in ids]
      
      return pdb.get(key_strings,**kwds)
    
    @classmethod
    def get_or_insert(cls,key_name,**kwds):
      '''Retrieve or create an instance of Model class using the given storage layers.
      
      Args:
        _storage: string or array of strings for target storage layers  
        _local_expiration: Time in seconds for local cache expiration for models
        _memcache_expiration: Time in seconds for memcache expiration for models
        Inherited:
          key_name: Key name to retrieve or create.
          **kwds: Keyword arguments to pass to the constructor of the model class
            if an instance for the specified key name does not already exist. If
            an instance with the supplied key_name and parent already exists, the
            rest of these arguments will be discarded.

      Returns:
        Existing instance of Model class with the specified key_name and parent
        or a new one that has just been created.
  
      Raises:
        TransactionFailedError if the specified Model instance could not be
        retrieved or created transactionally (due to high contention, etc).
      '''
      
      def txn():
        entity = cls(key_name=key_name, **kwds)
        entity.put(**kwds)
        return entity
    
      entity = cls.get_by_key_name(key_name,parent=kwds.get('parent'))
      if entity is None:
        return db.run_in_transaction(txn)
      else:
        return entity

    def clone_entity(self,**extra_args):
      """Clones an entity, adding or overriding constructor attributes.
      
          The cloned entity will have exactly the same property values as the original
          entity, except where overridden. By default it will have no parent entity or
          key name, unless supplied.
      
      Args:
          e: The entity to clone
          extra_args: Keyword arguments to override from the cloned entity and pass
          to the constructor.
      Returns:
          A cloned, possibly modified, copy of entity e.
        """
      klass = self.__class__
      props = {}
        
      for k,v in klass.properties().iteritems():
        if isinstance(v, db.ReferenceProperty):
          props[k] = v.get_value_for_datastore(self)
        else:
          props[k] = v.__get__(self,klass)
              
      props.update(extra_args)
      return klass(**props)
    
    def log_properties(self):
      '''Log properties of an entity'''
      for k,v in self.properties().iteritems():
        logging.info('%s : %s' %(k,v.get_value_for_datastore(self)))  
  
  class GqlQuery(db.GqlQuery):
      pass


class ResultTypeError(Exception):
  def __init__(self,type):
    self.type = type
  def __str__(self):
    return  'Result type is invalid: %s. Valid values are "list" and "dict" and "key_name dict"' %self.type
 
class StorageLayerError(Exception):
  def __init__(self,storage):
    self.storage = storage
  def __str__(self):
    return  'Storage layer name invalid: %s. Valid values are "local","memcache" and "datastore"' %self.storage

class KeyParameterError(Exception):
  def __init__(self,param):
    self.type = type(param)
  def __str__(self):
      return  '%s was given as function parameter, it should be db.Key,String or db.Model' %self.type
       
class IdentifierNotFoundError(Exception):
    def __str__(self):
        return  'Error trying to write models into cache without valid identifiers. Try enabling datastore write for the models or use keynames instead of IDs.'
