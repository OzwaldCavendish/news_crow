"""
Martin Wood - 03/08/2020
Functions for reporting on the coherence of a corpus
"""

import re
import gensim
import spacy
import random

import numpy as np
import pandas as pd
import networkx as nx

import seaborn as sns
import matplotlib.pyplot as plt

from collections import Counter
from datetime import datetime as dt
from gensim.models.coherencemodel import CoherenceModel
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer

from lib.helper import flatten, preprocess_description

nlp = spacy.load('en_core_web_sm')

# Switches off "setting on slice of dataframe" warning
pd.set_option('mode.chained_assignment', None)


def text_rank_summary(df, n_returns=5):
    """
    Take all documents in a cluster, extract most exemplary
    """
    # Sanity check; any actual documents?
    if len(df) == 0:
        return None
    
    df['sentences'] = df['tokens'].apply(" ".join)
    
    # Find vectors for all sentences
    vectorizer = TfidfVectorizer(max_features=300)
    vectors = vectorizer.fit_transform(df['sentences'])
    
    # Get the cosine similarity between pairs of sentences
    sim_mat = cosine_similarity(vectors)
    
    # Build the similarity graph
    sim_graph = nx.from_numpy_array(sim_mat)
    scores = nx.pagerank(sim_graph)
    
    ranked_sentences = sorted(((scores[i], s) for i,s in enumerate(df['clean_text'])), reverse=True)
    
    return ranked_sentences[:n_returns]


def entities_summary(df, n_returns=10):
    """
    Take all the entities in a cluster, extract most frequently named
    """
    def get_entities(doc):
        return [ent for ent in nlp(doc).ents]
    
    document_entities = df['clean_text'].apply(get_entities)
    
    return Counter([entity for entity in [str(x).upper() for x in flatten(document_entities)]]).most_common(n_returns)
    
    
def nouns_summary(df, n_returns=10):
    """
    Take all the entities in a cluster, extract most frequently named
    """
    def get_nouns(doc):
        return [token.text for token in nlp(doc) if token.pos_ == 'PROPN']
    
    document_nouns = df['clean_text'].apply(get_nouns)
    
    return Counter([noun for noun in [str(x).upper() for x in flatten(document_nouns)]]).most_common(n_returns)
    
    
def get_cluster_summary(df):
    """
    Wrapper for reporting example text from a cluster
    """
    return {"examples": text_rank_summary(df),
            "entities": entities_summary(df),
            "nouns": nouns_summary(df)}

    
def time_coherence(df, cluster_id):
    """
    Calculate the average (mean) time gap between successive stories
    Ignores NA's
    Returns seconds
    """
    subset = df[df['cluster']==cluster_id].sort_values('date_clean')

    subset['date_diff'] = (subset['date_clean'] - subset['date_clean'].shift()).astype('timedelta64[s]')

    return sum(subset['date_diff'].dropna()) / len(subset['date_diff'].dropna())


def macro_time_coherence(df, cluster_column="cluster"):
    """
    Calculate macro-average time coherence for a corpus
    """
    
    df['date_clean'] = pd.to_datetime(df['date'], errors='coerce', utc=True)
    
    cluster_ids = list(pd.unique(df[cluster_column]))
    
    # Don't bother with outliers
    if -1 in cluster_ids:
        cluster_ids.remove(-1)
    
    time_coherences = []
    for cluster_id in cluster_ids:
        try:
            time_coherences.append(time_coherence(df, cluster_id))
        except Exception as e:
            print("Time coherence calculation failed on ", cluster_id)
            print(e)
    
    return sum(time_coherences) / len(time_coherences)


def micro_time_coherence(df, cluster_column="cluster"):
    """
    Calculate macro-average time coherence for a corpus
    """
    
    df['date_clean'] = pd.to_datetime(df['date'], errors='coerce', utc=True)
    
    cluster_ids = list(pd.unique(df[cluster_column]))
    
    # Don't bother with outliers
    if -1 in cluster_ids:
        cluster_ids.remove(-1)
    
    time_coherences = []
    for cluster_id in cluster_ids:
        try:
            time_coherences.append(time_coherence(df, cluster_id) * (sum(df[cluster_column]==cluster_id) / len(df)))
        except Exception as e:
            print("Time coherence calculation failed on ", cluster_id)
            print(e)
    
    return sum(time_coherences)


def get_corpus_time_coherence(df, cluster_column="cluster"):
    """
    Returns information on how coherent a clustering solution for a corpus
    is in time, as well as time coherence by topic.
    Reporting units are seconds.
    """
    
    # Get average corpus coherences
    micro = micro_time_coherence(df, cluster_column=cluster_column)
    macro = macro_time_coherence(df, cluster_column=cluster_column)
    
    # Get coherence by cluster
    cluster_coherences = {}
    cluster_sizes = {}
    for cluster_id in list(pd.unique(df[cluster_column])):
        cluster_coherences[cluster_id] = time_coherence(df, cluster_id)
        cluster_sizes[cluster_id] = len(df[df[cluster_column]==cluster_id])
        
    tabulated = pd.DataFrame({"topic_labels": list(cluster_coherences.keys()),
                              "time_coherence": list(cluster_coherences.values()),
                              "topic_sizes": list(cluster_sizes.values())})
    
    return {"micro_time_coherence": micro,
            "macro_time_coherence": macro,
            "topic_features": tabulated}


def get_corpus_model_coherence(df, cluster_column="cluster"):
    """ 
    Encapsulates entire coherence model-building process for (flat) models
    """
    # Create the vocabulary record
    bow_dictionary = gensim.corpora.Dictionary(list(df["tokens"]))
    
    # Create a BOW model
    bow_corpus = [bow_dictionary.doc2bow(doc) for doc in df["tokens"]]
    
    # Flattened list of all tokens for all documents for each "topic"
    topics = {}
    topics_lengths = {}
    
    topic_labels = [x for x in pd.unique(df['cluster']) if x != -1]
    
    for topic in topic_labels:
        subset = df[df['cluster'] == topic]
        topics_lengths[topic] = subset.shape[0]
        topics[topic] = flatten(list(subset['tokens']))
    
    # Calculate ALL THE COHERENCE
    coherence_models = {}
    
    # c_v is most performant indirect confirmation measure
    cm1 = CoherenceModel(topics=list(topics.values()),
                         texts=list(df['tokens']),
                         dictionary=bow_dictionary,
                         coherence='c_v')
    coherence_models['c_v'] = cm1
    
    # c_npmi is most performant direct confirmation measure (that I don't have to implement myself)
    cm2 = CoherenceModel(topics=list(topics.values()),
                         texts=list(df['tokens']),
                         dictionary=bow_dictionary,
                         coherence='c_npmi')
    coherence_models['c_npmi'] = cm2
    
    return(coherence_models, topics_lengths)


def report_corpus_model_coherence(data_path, cluster_column="cluster", text_column="clean_text", max_size=None):
    """
    Creates two key coherence models (C_v, NPMI) and reports coherences,
    plus coherence/topic distribution
    """
    df = pd.read_csv(data_path)
    df["tokens"] = df[text_column].apply(preprocess_description)
    
    # If cluster is larger than maximum limit, designate as outlier
    if max_size:
        cs_lookup = df[cluster_column].value_counts().to_dict()
        df[cluster_column] = df[cluster_column].apply(lambda x: -1 if (cs_lookup[x] > max_size) else x)
    
    # Handles the coherence scoring
    coherence_models, topics_lengths = get_corpus_model_coherence(df, cluster_column=cluster_column)
    
    # Gather scores by topic/cluster for different metrics
    topics_results = {}
    
    time_stats = get_corpus_time_coherence(df, cluster_column="cluster")
    topics_results['time'] = time_stats['topic_features']
    
    for key in coherence_models.keys():
        
        # Extract the model scores and sizes
        topic_features = pd.DataFrame({"topic_labels": list(topics_lengths.keys()),
                                       "topic_coherence": list(coherence_models[key].get_coherence_per_topic()),
                                       "topic_sizes": list(topics_lengths.values())})
            
        topics_results[key] = topic_features
        
    fig, axs = plt.subplots(nrows=1, ncols=2, figsize=(10, 5))
    
    # Get key info from the filepath and use as a title
    #fig.suptitle(data_path.split("/")[1].strip(".csv").upper().replace("_", " "))
        
    temp = topics_results['c_v'][topics_results['c_v']['topic_labels'] != -1]
    time = topics_results['time'][topics_results['time']['topic_labels'] != -1]
    
    # Time Coherence
    #sns.scatterplot(x='topic_sizes', y='time_coherence', data=time, ax=axs[0])
    #axs[0].set_xlabel("N. Docs in Cluster")
    #axs[0].set_ylabel("Cluster Coherence in Time (s)")
    
    temp['topic_coherence'].hist(ax=axs[0], bins=30)
    axs[0].set_xlabel("Cluster Topic Coherence (Cv)")
    axs[0].set_ylabel("Number of Clusters")
    
    sns.scatterplot(x='topic_sizes', y='topic_coherence', data=temp, ax=axs[1])
    axs[1].set_xlabel("N. Docs in Cluster")
    axs[1].set_ylabel("Cluster Topic Coherence (Cv)")
    
    plt.savefig("outputs/" + data_path.split("/")[1].strip(".csv") + ".png")
    
    stats = {}
    
    # Coherence stats
    for key in coherence_models.keys():
        stats[key] = round(coherence_models[key].get_coherence(), 4)
    stats['macro_time_coherence'] = time_stats['macro_time_coherence']
    stats['micro_time_coherence'] = time_stats['micro_time_coherence']
    
    # General stats
    df['doc_size'] = df['clean_text'].apply(lambda x: len(x.split()))
    stats["Average document word count"] = np.mean(df['doc_size'])
    stats["Number of documents"] = df.shape[0]
    stats["Latest record"] = min(df['date'])
    stats["Earliest record"] = max(df['date'])
    stats["Number of clusters"] = len(pd.unique(df['cluster']))
    stats["Median cluster size"] = np.median(topic_features['topic_sizes'])
    stats["Percent clustered docs"] = round(100.0 * sum(df[cluster_column] != -1) / df.shape[0], 1)
    
    # Get four examples for each of four most coherent
    top_topics = list(topics_results['c_v'].sort_values("topic_coherence", ascending=False)['topic_labels'])[:4]
    
    stats["examples_best_performant"] = [get_cluster_summary(df[df[cluster_column]==x]) for x in top_topics]
    
    # Get four examples for each of four least coherent
    bot_topics = list(topics_results['c_v'].sort_values("topic_coherence", ascending=True)['topic_labels'])[:4]
    
    stats["examples_worst_performant"] = [get_cluster_summary(df[df[cluster_column]==x]) for x in bot_topics]
    
    # Get four examples for each of four most populous
    pop_topics = list(topics_results['c_v'].sort_values("topic_sizes", ascending=False)['topic_labels'])[:4]
    
    stats["examples_populous"] = [get_cluster_summary(df[df[cluster_column]==x]) for x in pop_topics]
    
    return stats, coherence_models, topics_results


def format_examples(examples_dict, len_limit=4):
    """
    Utility for formatting examples from a cluster into the format that
    LaTeX uses.
    """
    return pd.DataFrame({"TextRank Score": [x[0] for x in examples_dict['examples']][:len_limit],
                         "Text": [x[1][:120] for x in examples_dict['examples']][:len_limit],
                         "Entities": [x[0] for x in examples_dict['entities']][:len_limit],
                         "Entities Count": [x[1] for x in examples_dict['entities']][:len_limit]})
    