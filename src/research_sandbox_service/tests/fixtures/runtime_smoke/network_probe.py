import socket


probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
probe.close()
