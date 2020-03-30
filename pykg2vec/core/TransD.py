#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf

from pykg2vec.core.KGMeta import ModelMeta
from pykg2vec.utils.generator import TrainingStrategy

class TransD(ModelMeta):
    """ `Knowledge Graph Embedding via Dynamic Mapping Matrix`_

        TransD constructs a dynamic mapping matrix for each entity-relation pair by considering the diversity of entities and relations simultaneously.
        Compared with TransR/CTransR, TransD has fewer parameters and has no matrix vector multiplication.

        Args:
            config (object): Model configuration parameters.

        Attributes:
            config (object): Model configuration.
            model_name (str): Name of the model.
            data_stats (object): Class object with knowlege graph statistics.

        Examples:
            >>> from pykg2vec.core.TransD import TransD
            >>> from pykg2vec.utils.trainer import Trainer
            >>> model = TransD()
            >>> trainer = Trainer(model=model)
            >>> trainer.build_model()
            >>> trainer.train_model()

        Portion of the code based on `OpenKE_TransD`_.

        .. _OpenKE_TransD:
            https://github.com/thunlp/OpenKE/blob/master/models/TransD.py

        .. _Knowledge Graph Embedding via Dynamic Mapping Matrix:
            https://www.aclweb.org/anthology/P15-1067
    """

    def __init__(self, config):
        super(TransD, self).__init__()
        self.config = config
        self.model_name = 'TransD'
        self.training_strategy = TrainingStrategy.PAIRWISE_BASED

    def def_parameters(self):
        """Defines the model parameters.

           Attributes:
               num_total_ent (int): Total number of entities.
               num_total_rel (int): Total number of relations.
               k (Tensor): Size of the latent dimesnion for relations.
               d (Tensor): Size of the latent dimesnion for entities .
               ent_embeddings (Tensor Variable): Lookup variable containing  embedding of the entities.
               rel_embeddings  (Tensor Variable): Lookup variable containing  embedding of the relations.

               ent_mappings (Tensor Variable): Lookup variable containing  mapping for entities.
               rel_mappings   (Tensor Variable): Lookup variable containing   mapping for relations.
               parameter_list  (list): List of Tensor parameters.
        """
        num_total_ent = self.config.kg_meta.tot_entity
        num_total_rel = self.config.kg_meta.tot_relation
        d = self.config.ent_hidden_size
        k = self.config.rel_hidden_size

        emb_initializer = tf.initializers.glorot_normal()

        self.ent_embeddings = tf.Variable(emb_initializer(shape=(num_total_ent, d)), name="ent_embedding")
        self.rel_embeddings = tf.Variable(emb_initializer(shape=(num_total_rel, k)), name="rel_embedding")
        self.ent_mappings   = tf.Variable(emb_initializer(shape=(num_total_ent, d)), name="ent_mappings")
        self.rel_mappings   = tf.Variable(emb_initializer(shape=(num_total_rel, k)), name="rel_mappings")

        self.parameter_list = [self.ent_embeddings, self.rel_embeddings, self.ent_mappings, self.rel_mappings]

    def embed(self, h, r, t):
        """Function to get the embedding value.

           Args:
               h (Tensor): Head entities ids.
               r (Tensor): Relation ids of the triple.
               t (Tensor): Tail entity ids of the triple.

            Returns:
                Tensors: Returns head, relation and tail embedding Tensors.
        """
        emb_h = tf.nn.embedding_lookup(self.ent_embeddings, h)
        emb_r = tf.nn.embedding_lookup(self.rel_embeddings, r)
        emb_t = tf.nn.embedding_lookup(self.ent_embeddings, t)

        h_m = tf.nn.embedding_lookup(self.ent_mappings, h)
        r_m = tf.nn.embedding_lookup(self.rel_mappings, r)
        t_m = tf.nn.embedding_lookup(self.ent_mappings, t)

        emb_h = self.projection(emb_h, h_m, r_m)
        emb_t = self.projection(emb_t, t_m, r_m)

        return emb_h, emb_r, emb_t

    def dissimilarity(self, h, r, t, axis=-1):
        """Function to calculate distance measure in embedding space.

        Args:
            h (Tensor): shape [b, k] Head entities in a batch. 
            r (Tensor): shape [b, k] Relation entities in a batch.
            t (Tensor): shape [b, k] Tail entities in a batch.
            axis (int): Determines the axis for reduction

        Returns:
            Tensor: shape [b] the aggregated distance measure.
        """
        norm_h = tf.nn.l2_normalize(h, axis=axis)
        norm_r = tf.nn.l2_normalize(r, axis=axis)
        norm_t = tf.nn.l2_normalize(t, axis=axis)
        
        dissimilarity = norm_h + norm_r - norm_t 

        if self.config.L1_flag:
            dissimilarity = tf.math.abs(dissimilarity) # L1 norm 
        else:
            dissimilarity = tf.math.square(dissimilarity) # L2 norm
        
        return tf.reduce_sum(dissimilarity, axis=axis)

    def get_loss(self, pos_h, pos_r, pos_t, neg_h, neg_r, neg_t):
        """Defines the loss function for the algorithm."""
        pos_h_e, pos_r_e, pos_t_e = self.embed(pos_h, pos_r, pos_t)
        pos_score = self.dissimilarity(pos_h_e, pos_r_e, pos_t_e)

        neg_h_e, neg_r_e, neg_t_e = self.embed(neg_h, neg_r, neg_t)      
        neg_score = self.dissimilarity(neg_h_e, neg_r_e, neg_t_e)

        loss = self.pairwise_margin_loss(pos_score, neg_score)

        return loss

    def predict_rank(self, h, r, t, topk=-1):
        """Function that performs prediction for TransE. 
           shape of h can be either [num_tot_entity] or [1]. 
           shape of t can be either [num_tot_entity] or [1].

          Returns:
              Tensors: Returns ranks of head and tail.
        """
        h_e, r_e, t_e = self.embed(h, r, t)
        score = self.dissimilarity(h_e, r_e, t_e)
        _, rank = tf.nn.top_k(score, k=topk)

        return rank

    def projection(self, emb_e, emb_m, proj_vec):
        # [b, k] + sigma ([b, k] * [b, k]) * [b, k]
        return emb_e + tf.reduce_sum(emb_e * emb_m, axis=-1, keepdims=True) * proj_vec