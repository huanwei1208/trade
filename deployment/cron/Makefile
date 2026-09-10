DAGS := /home/peng/etc/docker/dagu/dags/trade

deploy: deploy-cn deploy-us

deploy-cn:
	cp trade-daily.yaml $(DAGS)/trade-daily.yaml

deploy-us:
	cp us-daily.yaml $(DAGS)/us-daily.yaml

.PHONY: deploy deploy-cn deploy-us
