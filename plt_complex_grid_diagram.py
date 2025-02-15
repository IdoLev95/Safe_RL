from envs.ours.complex_grid.complex_grid import Complex_Grid
import copy

env = Complex_Grid()

occcupancy = copy.deepcopy(env.occupancy)
array_1 = env.occupancy
array_2 = env.frozen


size = env.size

G = env.goal
k = 0
i = 0
"""
1: Walls
0: Can Move
-1: pit
2: Gooal
3: Start
4: Sub Goals
"""


while i != G + 1:

    if occcupancy[k // len(occcupancy)][k % len(occcupancy)] == 0:

        if i == G:
            array_1[k // len(array_1)][k % len(array_1)] = 2
        i += 1
    k += 1

#for start state
S = 1 #start
k = 0
i = 0
while i != S + 1:

    if occcupancy[k // len(occcupancy)][k % len(occcupancy)] == 0:

        if i == S:
            array_1[k // len(array_1)][k % len(array_1)] = 3
        i += 1
    k += 1


#for sub goals
for N in [43, 42, 101, 136, 169]:

    i = 0
    k = 0
    while i != N+1:
        if occcupancy[k//len(occcupancy)][k%len(occcupancy)] == 0:

            if i == N:
                array_1[k // len(array_1)][k % len(array_1)] = 4
            i += 1
        k += 1


costs = []
costs_car = []

for i in range(len(array_2)):
    for j in range(len(array_2[0])):

        if array_2[i][j] == 1:
            costs.append(env.tostate[(i, j)])
            costs_car.append((i,j))

            array_1[i][j] = -1
"""

A = [88, 87, 77, 67, 61, 60, 61, 60, 59, 58, 51, 42, 43, 44, 45, 35, 24, 23, 24, 25]
B = [26, 36, 37, 27, 37, 38, 39, 49]
Costs = [1, 8, 16, 22, 28, 32, 48, 53, 58, 69, 70, 71, 73, 78, 79, 80, 81, 82, 89, 90, 95, 101]
print(costs)
print(costs_car)
print(env.tostate[7,2])
array_x = copy.deepcopy(array_1)



for N in A:

    i = 0
    k = 0
    while i != N+1:

        if occcupancy[k//len(occcupancy)][k%len(occcupancy)] == 0:
            i += 1
            if i == N:
                array_x[k // len(array_x)][k % len(array_x)] = 5
        k += 1


for N in B:

    i = 0
    k = 0
    while i != N+1:

        if occcupancy[k//len(occcupancy)][k%len(occcupancy)] == 0:
            i += 1
            if i == N:
                array_x[k // len(array_x)][k % len(array_x)] = 5
        k += 1

"""



import matplotlib.pyplot as plt
from matplotlib import colors
import numpy as np

data = array_1

print(data)
# create discrete colormap
cmap = colors.ListedColormap(['red', 'white', "black", "green", "blue", "yellow"])
bounds = [-2, -0.5, 0.5, 1.5, 2.5, 3.5, 4.5]
norm = colors.BoundaryNorm(bounds, cmap.N)


fig, ax = plt.subplots()
ax.imshow(data, cmap=cmap, norm=norm)

# draw gridlines
ax.grid(which='major', axis='both', linestyle='-', color='k', linewidth=2, )
ax.legend=['red', 'white', "black", "green", "blue", "yellow"]
ax.set_xticks(np.arange(-0.5, 16.5, 1))
ax.set_yticks(np.arange(-0.5, 16.5, 1))

plt.show()

cmap = colors.ListedColormap(['red', 'white', "black", "green", "blue", "yellow", "orange"])
bounds = [-2, -0.5, 0.5, 1.5, 2.5, 3.5, 4.5, 5.5]
norm = colors.BoundaryNorm(bounds, cmap.N)


fig, ax = plt.subplots()
ax.imshow(array_x, cmap=cmap, norm=norm)

# draw gridlines
ax.grid(which='major', axis='both', linestyle='-', color='k', linewidth=2, )
ax.legend=['red', 'white', "black", "green", "blue", "yellow"]
ax.set_xticks(np.arange(-0.5, 27.5, 1))
ax.set_yticks(np.arange(-0.5, 27.5, 1))

plt.show()