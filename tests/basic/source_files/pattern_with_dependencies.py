# source_files/program_4.py

from qiskit_serverless import save_result

import pendulum

dt_toronto = pendulum.datetime(2012, 1, 1, tz='America/Toronto')
dt_vancouver = pendulum.datetime(2012, 1, 1, tz='America/Vancouver')

diff = dt_vancouver.diff(dt_toronto).in_hours() 

print(diff)
save_result({"hours": diff})
