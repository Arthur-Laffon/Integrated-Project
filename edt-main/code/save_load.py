import pickle
import os

#data is stored in ./data/data.pkl
filename = "data/data.pkl"

def store(data):
    """
    Take data as argument and store it in ./data/data.pkl 
    """
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'wb') as file:
        pickle.dump(data, file)

def load():
    """
    if ./data/data.pkl exists then load its data and return it else return None
    """
    if os.path.isfile(filename):
        with open(filename, 'rb') as file:
            data_loaded = pickle.load(file)
            return data_loaded
    return None #if the file doesnt exists