import Levenshtein

s1 = "Ask your grandpa"
s2 = "Ask your grandpa again"

distance = Levenshtein.distance(s1, s2)
similarity = 1 - distance / max(len(s1), len(s2))

print(distance)
print(similarity)
