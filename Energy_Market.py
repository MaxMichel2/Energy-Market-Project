import random
import sys
import threading
from multiprocessing import Manager, Value, Process, Lock, Event, Array, Pipe, Queue
import os
import time

renew_season_coef = [[1, 1, 1, 1], 
					[1.23, 1.3, 1.1, 1.08],
					[1.07, 1.09, 1.24, 1.27]]
delay = 2.5
starting_price = 0.15

gamma = 0.99
alpha_1 = 0.001
alpha_2 = 0.01
alpha_3 = 0.05
beta_1 = 0.01
beta_2 = 0.5

energy_scale = 0.1
credit_scale = 0.5
					
def home(number_of_homes, renewable_energy, policy, queue_lock, counter_lock, write_lock, home_queue, market_queue, energy_exchange_queue, home_counter, market_ready, temperature, season, weather_ready, clock_ready):
	id = int(os.getpid())
	credit_balance = 0
	
	while clock_ready.wait(1.5 * delay):
	
		market_flag = False
		deficit_flag = False
		
		weather_ready.wait()
		consumption = random.random() * temperature[1]
		production = random.random()
		# 0 = always sell to market, 1 = always give away, 2 = sell if no takers
		current_season = int(season[1])
		production *= renew_season_coef[renewable_energy][current_season]
		energy_balance = production - consumption
		
		with queue_lock:
			market_queue.put([id, energy_balance])
		
		if energy_balance < 0:
			with queue_lock:
				home_queue.put([id, energy_balance])
			with counter_lock:
				home_counter.value += 1
		
		else:
			with counter_lock:
				home_counter.value += 1
				
		while home_counter.value < number_of_homes:
			True
			
		clock_ready.clear()
		weather_ready.clear()
		
		if energy_balance > 0 and (policy == 1 or policy == 2):
		
			with queue_lock:
				while (energy_balance != 0 and (not home_queue.empty() or home_queue.qsize() != 0)):
					request = home_queue.get()
					
					if abs(request[1]) <= energy_balance:
						energy_balance -= abs(request[1])
						energy_exchange_queue.put([id, abs(request[1]), request[0]])
					
					else:
						home_queue.put([request[0], request[1] + energy_balance])
						energy_exchange_queue.put([id, energy_balance, request[0]])
						energy_balance = 0
					
		with counter_lock:
			home_counter.value += 1
			
		while home_counter.value < 2 * number_of_homes:
			True
			
		if energy_balance < 0:
			other_requests = []
			
			with queue_lock:
				while not home_queue.empty() or home_queue.qsize() != 0:
					request = home_queue.get()
					if request[0] == id:
						energy_balance = request[1]
						deficit_flag = True
						break
					else:
						other_requests.append(request)
				
				for req in other_requests:
					home_queue.put(req)
					
			if deficit_flag == False:
				energy_balance = 0
				
		with queue_lock:
			market_queue.put([id, energy_balance])
			
		if (energy_balance < 0 and policy == 1) or (energy_balance != 0 and policy != 1):
			with queue_lock:
				home_queue.put([id, energy_balance])
				market_flag = True
			
			energy_balance = 0
			
		if (energy_balance > 0 and policy == 1):
			energy_balance = 0
			
		with counter_lock:
			home_counter.value += 1
			
		deficit_flag = False

		while market_ready.value == False:
			True
		
		if market_flag:
			other_requests_2 = []
			
			with queue_lock:
				while market_flag:
					request = home_queue.get()
					
					if request[0] == id:
						credit_balance += request[1]
						market_flag = False
					else:
						other_requests_2.append(request)
						
				for req in other_requests_2:
					home_queue.put(req)
					
		home_counter.value = 0
		
		with queue_lock:
			market_queue.put([id, credit_balance])
		
def market(number_of_days, number_of_homes, home_queue, home_counter, market_ready, clock_ready, temperature, season, market_connection):
	current_price = starting_price
	average_exchange = 0.0
	exchange = 0.0
	
	market_conn, external_conn = Pipe()
	
	e = Process(target = external, args=(external_conn, clock_ready, number_of_days))
	e.start()
	
	while clock_ready.wait(1.5 * delay):
		market_ready.value = False
		event = market_conn.recv()
		internal_effect = alpha_1 * temperature[1] + alpha_3 * average_exchange
		external_effect = event[1] * event[2]
		
		current_price = gamma * current_price + internal_effect + external_effect
		
		if current_price < 0.02:
			current_price = 0.02
			print("Negative price changed to 0.02 €/kW")
			
		if current_price > 2.0:
			current_price = 2.0
			print("Exploded price changed to 2 €/kW")
			
		market_conn.send([current_price, event[0], event[1], event[2], average_exchange])
		
		while home_counter.value < 3 * number_of_homes:
			True
			
		number_of_requests = home_queue.qsize()
		requests = []
		
		for i in range(number_of_requests):
			request = home_queue.get()
			requests.append(request)
		
		for req in requests:
			home_queue.put([req[0], req[1] * current_price])
			
		market_ready.value = True
		exchange = 0.0
		
		for req in requests:
			exchange += req[1]
			
		try:
			average_exchange = exchange / number_of_requests
		except:
			average_exchange = 0
			
	e.join()
	
def clock(clock_ready, number_of_days):
	c = 0
	
	while c < number_of_days:
		clock_ready.set()
		c += 1
		initial_time = time.time()
		
		while time.time() - initial_time < delay:
			time.sleep(2)
			
def weather(temp, seas, clock_ready, weather_ready, weather_connection):
	temp[0] = alpha_1
	seas[0] = alpha_2
	
	while clock_ready.wait(1.5 * delay):
		temp[1] = round(random.gauss(10.0, 5.0), 2)
		seas[1] = float(random.randint(0, 3))
		weather_connection.send([temp[1], seas[1]])
		# 0 is Spring
		# 1 is Summer
		# 2 is Autumn
		# 3 is Winter
		temp[1] = 1/((temp[1]+6.0)/(15.0+6.0))
		weather_ready.set()
		time.sleep(delay/2)
			
def external(external_connection, clock_ready, number_of_days):
	events = [["Nuclear fusion", 0.4, -0.3],
			 ["Civil war", 0.5, 0.2],
			 ["Reelection of Trump", 0.3, 0.3],
			 ["Biofuel conversion for all vehicles", 0.3, -0.2],
			 ["Climate change brings Ice Age", 0.35, 0.33]]
			 
	for i in range(number_of_days):
		event = False
		rand = random.random()
		
		if rand >= 0.75:
			event = True
			
		if event:
			external_connection.send(events[random.randint(0, len(events) - 1)])
		else:
			external_connection.send(["None", 0, 0])
			
def terminal(number_of_homes, market_queue, home_counter, clock_ready, energy_exchange_queue, console_connection, console_connection_2):
	day = 1
	
	while clock_ready.wait(1.5 * delay):
		req1, req2, req3, req4 = ([] for i in range(4))
		
		for i in range(number_of_homes):
			a = market_queue.get()
			req1.append(a)
		req1 = sort(req1)
		
		for i in range(number_of_homes):
			a = market_queue.get()
			req1.append(a)
		req2 = sort(req2)
		
		for i in range(number_of_homes):
			a = market_queue.get()
			req1.append(a)
		req3 = sort(req3)
		
		req1 = req1 + req2 + req3
		
		for i in range(energy_exchange_queue.qsize()):
			b = energy_exchange_queue.get()
			req4.append(b)
		req4 = sort(req4)
		
		thread = threading.Thread(target = console_display, args = (number_of_homes, req1, day, req4, console_connection.recv(), console_connection_2.recv()))
		thread.start()
		thread.join()

		day += 1
		
def sort(requests):
	init_list = []
	curr_list = []
	final_list = []
	
	if len(requests) > 1:
		pivot_value = requests[0]
		for i in requests:
			if i < pivot_value:
				init_list.append(i)
			if i > pivot_value:
				final_list.append(i)
			if i == pivot_value:
				curr_list.append(i)
		
		return sort(init_list) + curr_list + sort(final_list)
		
	else:
		return requests

def console_display(number_of_homes, req1, day, req4, console_1, console_2):
	string_day = "DAY "+str(day)
	current_season = ""
	if console_2[1] == 0:
		current_season = "Spring"
	if console_2[1] == 1:
		current_season = "Summer"
	if console_2[1] == 2:
		current_season = "Autumn"
	if console_2[1] == 3:
		current_season = "Winter"
	
	print('{:-^70}'.format(string_day))
	print("")
	print("Temperature :", round(console_2[0], 3), "°C --> Change :", round(alpha_1/((console_2[0]+6.0)/(15.0+6.0)), 3), "€/kW | Season :", current_season)
	print("Average exchanges per day on day", day - 1,":", round(console_1[4], 3),"kW --> Change :", round((-alpha_3 * console_1[4]), 3),"€/kW")
	print("Current price :", round(console_1[0], 3), "€/kW | Current event :", console_1[1], "--> Modified price :", round(console_1[2] * console_1[3], 3), "€/kW")
	print('{:-^70}'.format(""))
	print("")
	
	for i in range(3):
		for j in range(j*number_of_homes, (j+1)*number_of_homes):
			number_of_symbols = int(req1[j][1]/energy_scale)
			if i != 2:
				if req1[j][1] >= energy_scale:
					print("Home", req1[j][0], "energy :", end = ' ')
					for k in range(number_of_symbols):
						sys.stdout.write('+')
					sys.stdout.flush()
			
				elif req1[j][1] <= -energy_scale:
					print("Home", req1[j][0], "energy :", end = ' ')
					for k in range(abs(number_of_symbols)):
						sys.stdout.write('-')
					sys.stdout.flush()
				
				else:
					print("Home", req1[j][0], "energy :", end = ' ')
					
				print(" ", round(req1[j][1], 3), "kW")
				
			if i == 2:
				number_of_symbols = int(req1[j][1]/credit_scale)
				if req1[j][1] >= credit_scale:
					print("Home", req1[j][0], "credit :", end = ' ')
					for k in range(number_of_symbols):
						sys.stdout.write('+')
					sys.stdout.flush()
					
				elif req1[j][1] <= -credit_scale:
					print("Home", req1[j][0], "credit :", end = ' ')
					for k in range(abs(number_of_symbols)):
						sys.stdout.write('-')
					sys.stdout.flush()
					
				else:
					print("Home", req1[j][0], "credit :", end = ' ')
					
				print(" ", round(req1[j][1], 3), "€")

		print('{:-^70}'.format(""))
		if i == 0 and len(req2) != 0:
			for k in range(len(req2)):
				print('{:/^60}'.format(" Home", req2[k][0], "gives", round(req2[k][1], 3), "kW to home", req2[k][2]))
				
			print((" "))
		
if __name__ == "__main__":
	start = time.time()
	number_of_homes = int(sys.argv[1])
	number_of_days = int(sys.argv[2])
	
	queue_lock = Lock()
	counter_lock = Lock()
	write_lock = Lock()
	
	home_queue = Queue()
	market_queue = Queue()
	energy_exchange_queue = Queue()
	
	clock_ready = Event()
	weather_ready = Event()
	
	home_counter = Value('i', 0)
	market_ready = Value('b', False)
	temperature = Array('f', range(2))
	season = Array('f', range(2))
	
	console_connection, market_connection = Pipe()
	console_connection_2, weather_connection = Pipe()
	
	homes = []
	
	for i in range(number_of_homes):
		renewable_energy = random.randint(0, 2)
		# 0 = normal home, 1 = solar, 2 = wind
		policy = random.randint(0, 2)
		home_process = Process(target = home, args = (number_of_homes, renewable_energy, policy, queue_lock, counter_lock, write_lock, home_queue, market_queue, energy_exchange_queue, home_counter, market_ready, temperature, season, weather_ready, clock_ready,),)
		home_process.start()
		
		if policy == 0:
			print("Home", i + 1, ": Always sell to market (", policy, ")")
			
		if policy == 1:
			print("Home", i + 1, ": Always give away (", policy, ")")
		
		if policy == 2:
			print("Home", i + 1, ": Sell if no takers (", policy, ")")
	
		homes.append(home_process)
		
	t = Process(target = terminal, args = (number_of_homes, market_queue, home_counter, clock_ready, energy_exchange_queue, console_connection, console_connection_2,))
	t.start()
	
	m = Process(target = market, args = (number_of_days, number_of_homes, home_queue, home_counter, market_ready, clock_ready, temperature, season, market_connection,))
	m.start()
	
	w = Process(target = weather, args = (temperature, season, clock_ready, weather_ready, weather_connection,))
	w.start()
	
	c = Process(target = clock, args = (clock_ready, number_of_days,))
	c.start()

	c.join()
	m.join()
	w.join()
	t.join()
	for h in Homes:
		h.join()
	
	print("Simulation duration :", (time.time() - start), "seconds")