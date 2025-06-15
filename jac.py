from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity

s1 = "WASM Part 3"
s2 = "The oracle"

vectorizer = CountVectorizer().fit_transform([s1, s2])
similarity = cosine_similarity(vectorizer[0], vectorizer[1])
print(similarity[0][0])
